import sys
import json
import requests
import logging
from collections import defaultdict
from argparse import ArgumentParser
from datetime import datetime
from urllib.parse import urlparse
import pytz
import os
import base64


# dev_kibana_url = 'https://e001708f0fe44a4d96341be1bf9a9943.us-east-1.aws.found.io:9243'
# qa_kibana_url = 'https://66f6f47a3ef14711adcaa97b8385a6ed.us-east-1.aws.found.io:9243'
# prod_kibana_url = 'https://a8d089aa7eb241639d5ba3dbd343cd29.us-east-1.aws.found.io:9243'
# ccs_kibana_url = 'https://287d86a4b1184182b340bd5074cdfd7e.us-east-1.aws.found.io:9243'


# Set up timestamp in EST
def set_timestamp():
    """Sets up a log file with the creation timestamp in its name using EST time."""
    # Define the EST timezone
    est_tz = pytz.timezone("US/Eastern")

    # Get the current timestamp in EST
    timestamp = datetime.now(est_tz).strftime("%Y_%m_%d_%H_%M_%S")
    return timestamp

# Setup Log file
def setup_log_file(timestamp):
    # Create the log file name with the EST timestamp
    log_file_name = f"log_file_{timestamp}.log"
    return log_file_name


# Configures logging to redirect logs and print statements to a custom log file
def setup_logging(log_file="output.log"):
    # Configure the root logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="w"),  # Overwrite log file each run
            logging.StreamHandler(sys.stdout),  # Print logs to stdout
        ],
    )

    # Redirect print statements to logging
    sys.stdout = LoggerWriter(logging.getLogger(), logging.INFO)
    sys.stderr = LoggerWriter(logging.getLogger(), logging.ERROR)


class LoggerWriter:
    """
    A file-like object to redirect print statements to the logging system.

    Args:
        logger (logging.Logger): Logger instance to write to.
        log_level (int): Logging level for the messages.
    """
    def __init__(self, logger, log_level):
        self.logger = logger
        self.log_level = log_level

    def write(self, message):
        if message.strip():  # Ignore empty messages
            self.logger.log(self.log_level, message.strip())

    def flush(self):
        pass  # No action needed for flush


# Initialize Kibana object types to be processed
def get_object_types():
    object_types = ["config", "config-global", "url", "index-pattern", "action", "query", "tag", "graph-workspace",
                    "alert", "search", "visualization", "event-annotation-group", "dashboard", "lens", "cases",
                    "metrics-data-source", "links", "canvas-element", "canvas-workpad", "osquery-saved-query",
                    "osquery-pack", "csp-rule-template", "map", "infrastructure-monitoring-log-view",
                    "threshold-explorer-view", "uptime-dynamic-settings", "synthetics-privates-locations",
                    "apm-indices", "infrastructure-ui-source", "inventory-view", "infra-custom-dashboards", "metrics-explorer-view",
                    "apm-service-group", "apm-custom-dashboards"]
    return object_types


# Set up headers for Kibana authentication
def get_headers(api_key):
    headers = {
        'kbn-xsrf': 'true',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {api_key}'
    }
    return headers


# Derive the GitHub REST API base and 'owner/repo' from a repo web URL.
# Works for github.com ('https://github.com/<owner>/<repo>') as well as a
# GitHub Enterprise host ('https://<host>/<owner>/<repo>'), so a future host
# change does not require editing the upload functions.
def parse_github_repo(repo_url):
    parsed = urlparse(repo_url)
    host = parsed.netloc
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    # Keep only '<owner>/<repo>' even if the URL has extra path segments
    owner_repo = "/".join(path.split("/")[:2])
    if host == "github.com":
        api_base = "https://api.github.com"
    else:
        # GitHub Enterprise Server REST API lives under /api/v3
        api_base = f"{parsed.scheme}://{host}/api/v3"
    return api_base, owner_repo


# Set up headers for github.com REST API authentication (token-based).
# github.com uses a Bearer Personal Access Token rather than Basic auth.
def get_github_headers(github_key):
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {github_key}',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    return headers


# Check-in files to a new github branch
def upload_file_to_github(repo_url, github_username, github_key, local_file_path, repo_file_path, github_branch, timestamp):
    commit_message = f"Uploaded object via script at {timestamp}"

    # Derive the REST API base and owner/repo from the repo URL, then build the
    # token-based auth headers for github.com.
    api_base, repo = parse_github_repo(repo_url)
    api_url = f"{api_base}/repos/{repo}"
    github_headers = get_github_headers(github_key)

    # Step 1: Get the default branch's SHA
    repo_info_url = f"{api_url}"
    repo_info_response = requests.get(repo_info_url, headers=github_headers)
    if repo_info_response.status_code != 200:
        print(f"Error retrieving repository info: {repo_info_response.status_code} : {repo_info_response.text}")
        raise Exception("Failed to retrieve repository information.")

    default_branch = repo_info_response.json().get("default_branch", "main")
    default_branch_url = f"{api_url}/git/ref/heads/{default_branch}"
    default_branch_response = requests.get(default_branch_url, headers=github_headers)
    if default_branch_response.status_code != 200:
        print(f"Error retrieving default branch '{default_branch}': {default_branch_response.text}")
        raise Exception("Default branch not found.")

    default_branch_sha = default_branch_response.json()["object"]["sha"]

    # Step 2: Create the new branch
    create_branch_url = f"{api_url}/git/refs"
    payload = {
        "ref": f"refs/heads/{github_branch}",
        "sha": default_branch_sha
    }
    create_branch_response = requests.post(create_branch_url, json=payload, headers=github_headers)
    if create_branch_response.status_code == 201:
        print(f"Branch '{github_branch}' created successfully.")
    else:
        print(f"Failed to create branch: {create_branch_response.status_code}, {create_branch_response.text}")
        raise Exception(f"Failed to create branch: {create_branch_response.text}")

    # Step 3: Read the local file and encode it
    with open(local_file_path, "rb") as file:
        content = base64.b64encode(file.read()).decode("utf-8")

    # Step 4: Prepare the payload for file upload
    file_url = f"{api_url}/contents/{repo_file_path}"
    payload = {
        "message": commit_message,
        "content": content,
        "branch": github_branch  # Specify the branch
    }

    # Step 5: Upload the file
    response = requests.put(file_url, json=payload, headers=github_headers)
    if response.status_code in (200, 201):
        print(f"File successfully uploaded to '{repo_url}/{repo_file_path}' on branch '{github_branch}'.")
    else:
        print(f"Failed to upload file: {response.status_code}, {response.text}")


# Check-in files to a the specified existing github branch
def upload_file_to_existing_github(repo_url, github_username, github_key, local_file_path, repo_file_path, github_branch, timestamp):
    # Commit message
    commit_message = f"Log file uploaded via script at {timestamp}"

    # Derive the REST API base and owner/repo from the repo URL, then build the
    # token-based auth headers for github.com.
    api_base, repo = parse_github_repo(repo_url)
    api_url = f"{api_base}/repos/{repo}/contents/{repo_file_path}"
    github_headers = get_github_headers(github_key)

    # Read the local file and encode it
    with open(local_file_path, "rb") as file:
        content = base64.b64encode(file.read()).decode("utf-8")

    # Prepare payload for file upload
    payload = {
        "message": commit_message,
        "content": content,
        "branch": github_branch
    }

    # Upload or update the file to Github
    response = requests.put(api_url, json=payload, headers=github_headers)
    if response.status_code in (200, 201):
        print(f"File successfully uploaded to '{repo_url}/{repo_file_path}' on branch '{github_branch}'.")
        print("")
    else:
        print(f"Failed to upload file: {response.status_code}, {response.text}")


# Retrieve all kibana objects in the current space
def retrieve_all_kibana_objects(headers, kibana_url, object_types):
    logging.info(f"Retrieving all Kibana objects in space: '{space_id}'...")
    find_objects_endpoint = f"{kibana_url}/s/{space_id}/api/saved_objects/_find"
    all_kib_objects = []
    # page = 1

    for object_type in object_types:
        params = {
            'type': object_type,
            'per_page': 10000
        }
        response = requests.get(find_objects_endpoint, headers=headers, params=params, verify=True)
        if response.status_code == 200:
            # response.raise_for_status()
            data = response.json()
            data = data.get("saved_objects", [])
            all_kib_objects.extend([{"id": obj["id"], "type": obj["type"]} for obj in data])
        else:
            logging.error(f"Failed to retrieve Kibana objects. Status code: {response.status_code}, Response: {response.text}")

    num_of_kibana_objects = len(all_kib_objects)
    logging.info(f"{num_of_kibana_objects} Kibana objects were found in this space: '{space_id}'")
    if num_of_kibana_objects == 0:
        print(f"There are NO Kibana objects in this space: '{space_id}'. No Further action is needed!")
        print(f"Exiting...")
        sys.exit(0)
    return all_kib_objects, num_of_kibana_objects


# Export all Kibana objects using the Saved Objects API and save to an NDJSON file.
def export_all_kibana_objects(all_kibana_objects, num_of_kibana_objects, headers, kibana_url, dry_run):
    export_objects_endpoint = f"{kibana_url}/s/{space_id}/api/saved_objects/_export"
    OUTPUT_FILE = "kibana_objects.ndjson"  # Path to save the exported objects
    logging.info(f"Exporting all Kibana objects in space: '{space_id}' to the '{OUTPUT_FILE}'. This would be used to restore all objects in case something goes wrong...")
    # NOTE: The export is a read-only Saved Objects _export call plus a local file
    # write (no Kibana mutation), so it runs in dry-run too, consistent with how
    # data-view backups and the log file are already checked in during dry-run.
    # This file is required by the GitHub backup step that follows.
    if num_of_kibana_objects > 0:
        payload = {
            "objects": all_kibana_objects,
            "includeReferencesDeep": True
        }
        response = requests.post(export_objects_endpoint, headers=headers, json=payload)
        if response.status_code == 200:
            with open(OUTPUT_FILE, "w") as file:
                file.write(response.text)
            logging.info(f"All {num_of_kibana_objects} Kibana objects are successfully backed-up to the '{OUTPUT_FILE}' file")
        else:
            logging.error(f"Failed to export objects. Status code: {response.status_code}, Response: {response.text}")
    else:
        logging.info(f"There are no Kibana objects to back-up. The '{OUTPUT_FILE}' file is not updated")
    return OUTPUT_FILE


# Function to get all data views in the space ID specified
def get_all_dataviews(space_id, headers, kibana_url):
    dataview_url = f'{kibana_url}/s/{space_id}/api/data_views'
    response = requests.get(dataview_url, headers=headers, verify=True)
    if response.status_code == 200:
        response = response.json()
        data_views = response['data_view']
    else:
        logging.error(f"Failed to GET all Data Views . Status code: {response.status_code}, Response: {response.text}")
    return data_views


# Function to find duplicated data views by title
def find_duplicated_data_views(data_views):
    title_to_ids = defaultdict(list)
    for data_view in data_views:
        title = data_view["title"]
        id = data_view["id"]
        title_to_ids[title].append(id)
    duplicates = {title: ids for title, ids in title_to_ids.items() if len(ids) > 1}
    return duplicates


# Retrieve all objects that references any duplicated data views, and count the number of references to each data view
def get_object_references(data_view_ids, kibana_url, space_id, object_types, headers):
    objects_endpoint = f"{kibana_url}/s/{space_id}/api/saved_objects/_find"
    reference_counts = defaultdict(int)

    all_objects = []
    for object_type in object_types:
        params = {
            'fields': 'references',
            'type': object_type,
            'per_page': 10000
        }
        response = requests.get(objects_endpoint, headers=headers, params=params, verify=True)
        response.raise_for_status()
        data = response.json()
        all_objects.extend(data.get("saved_objects", []))

    # Count each object's link to a data view
    for object in all_objects:
        references = object.get("references", [])
        for ref in references:
            if ref["type"] == "index-pattern" and ref["id"] in data_view_ids:
                reference_counts[ref["id"]] += 1
    return reference_counts, all_objects

# Scans the references list in a single saved object and updates the id for any reference where:
# reference.type is "index-pattern" & reference.id exactly equals old_dataview_id
# Returns a tuple (updated, new_references) where:
#   - updated is True if any reference was modified.
#   - new_references is the updated list of references.
def update_references(saved_object, old_dataview_id, new_dataview_id):
    updated = False
    new_refs = []
    for ref in saved_object.get("references", []):
        if ref.get("type") == "index-pattern" and ref.get("id") == old_dataview_id:
            new_ref = ref.copy()  # preserve name and any other properties
            new_ref["id"] = new_dataview_id
            updated = True
            new_refs.append(new_ref)
        else:
            new_refs.append(ref)
    return updated, new_refs

# Update the object's references field
def update_saved_object(object_type, object_id, updated_references, kibana_url, space_id, headers, dry_run):
    object_endpoint = f"{kibana_url}/s/{space_id}/api/saved_objects/{object_type}/{object_id}"
    payload = {
        "attributes": {},
        "references": updated_references
    }
    if dry_run:
        logging.info(f"[DRY-RUN] Would update object {object_id} with payload: {json.dumps(payload)}")
        return {"id": object_id, "dry_run": True}
    else:
        response = requests.put(object_endpoint, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


# Check if the any object is referencing the Data View to be Deleted
def has_references(all_objects, data_view_id):
    for object in all_objects:
        references = object.get("references", [])
        for ref in references:
            if ref['type'] == 'index-pattern' and ref['id'] == data_view_id:
                return True
    return False


def backup_data_view(kibana_url, headers, space_id, data_view_id, output_file):
    export_objects_endpoint = f"{kibana_url}/s/{space_id}/api/saved_objects/_export"
    payload = {
        "objects": [
            {
                "id": data_view_id,
                "type": "index-pattern"
            }
        ],
        "includeReferencesDeep": True
    }

    response = requests.post(export_objects_endpoint, headers=headers, json=payload)

    if response.status_code == 200:
        # Write the backup data to a file (one for each data view)
        with open(f"data_view_{data_view_id}_backup.ndjson", "w") as file:
            file.write(response.text)
        logging.info(f"Backup successful for data view: '{data_view_id}'! Saved to: 'data_view_{data_view_id}_backup.ndjson'")
    else:
        logging.error(f"Failed to backup data view {data_view_id}. Error: {response.text}")
        sys.exit(1)


# Delete Data View if it has no references by other Kibana Objects
def delete_dataview_if_no_references(data_view_id, all_objects, kibana_url, space_id, headers, dry_run):
    if dry_run:
        logging.info(f"[DRY-RUN] Would check if data view with id: '{data_view_id}' is referenced by any object. If no object is referecning this Data View, you would be prompted to choose if you want it deleted.")
        delete_data_view = input(f"Do you want this Data View with ID: {data_view_id} to be DELETED? Enter 'Y' for Yes, 'N' for No: ").upper()
        if delete_data_view == "Y":
            print(f"[DRY-RUN] Data View with ID: {data_view_id} would be DELETED \n")
        elif delete_data_view == "N":
            print(f"[DRY-RUN] Data View with ID: {data_view_id} would NOT be deleted \n")
        else:
            print(f"Invalid Entry. Re-run script and Enter 'Y' or 'N'")
        return None
    else:
        if not has_references(all_objects, data_view_id):
            dataview_url = f'{kibana_url}/s/{space_id}/api/data_views/data_view/{data_view_id}'
            print("")
            delete_data_view = input(f"Do you want this Data View with ID: {data_view_id} to be DELETED? Enter 'Y' for Yes, 'N' for No: ").upper()
            if delete_data_view == "Y":
                response = requests.delete(dataview_url, headers=headers)
                if response.status_code == 200:
                    print("")
                    print(f"Data view with ID {data_view_id} successfully DELETED.")
                else:
                    print("")
                    print(f"Failed to delete Old data view {data_view_id} . Status code: {response.status_code}, Response: {response.text}")
            elif delete_data_view == "N":
                print(f"You elected NOT to delete Data View with ID: {data_view_id}. Hence this Data View would NOT be deleted \n")
            else:
                print(f"Invalid Entry. Re-run script and Enter a valid entry: 'Y' or 'N'")
            return None
        else:
            print("")
            print(f"Data view {data_view_id} has references and was NOT deleted.")


# main
def main(kibana_url, headers, space_id, dry_run):
    log_file_name = setup_log_file(timestamp)
    setup_logging(log_file_name)  # Initialize logging
    updated_objects_count = 0
    data_views_to_be_deleted = []
    updated_objects = []


    print(f"RUNNING THE SCRIPT FOR SPACE: '{space_id}' IN ELASTIC CLUSTER: '{cluster_name}'")
    all_kibana_objects, num_of_kibana_objects = retrieve_all_kibana_objects(headers, kibana_url, object_types)
    kibana_objects = export_all_kibana_objects(all_kibana_objects, num_of_kibana_objects, headers, kibana_url, dry_run)
    local_file_path = f"{kibana_objects}"
    repo_file_path = f"all_objects/{local_file_path}"
    upload_file_to_github(repo_url, github_username, github_key, local_file_path, repo_file_path, github_branch, timestamp)
    data_views = get_all_dataviews(space_id, headers, kibana_url)
    duplicates = find_duplicated_data_views(data_views)
    print("")
    if not duplicates:
        logging.info("ALL CLEAR: No Duplicated Data views found!")
    else:
        dup_data_view_ids = []
        logging.warning("Duplicated data views found:")

        for title, ids in duplicates.items():
            # Get the reference counts for each data view ID in the duplicated group
            reference_counts, all_objects = get_object_references(ids, kibana_url, space_id, object_types, headers)
            print(f"DATA VIEW TITLE: {title}")
            for id in ids:
                print(f"  ID: {id}  : {reference_counts[id]} references")
                dup_data_view_ids.append(id)
                most_referenced_id = max(reference_counts, key=reference_counts.get)
                if id != most_referenced_id:
                    data_views_to_be_deleted.append(id)
                    for object in all_objects:
                        object_id = object.get("id")
                        object_type = object.get("type")
                        new_data_view_id = most_referenced_id
                        updated, new_refs = update_references(object, id, new_data_view_id)
                        if updated:
                            logging.info(f"Updating object {object_id} (type: {object_type}) with new data view id "
                                         f"(old: {id} -> new: {new_data_view_id})...")
                            update_resp = update_saved_object(object_type, object_id, new_refs, kibana_url, space_id, headers,
                                                              dry_run)
                            logging.info(f"Updated object {object_id}: {update_resp}")
                            updated_objects.append(object)
                            updated_objects_count += 1
    if updated_objects:
        if dry_run:
            logging.info("[DRY-RUN] The following objects would be updated:")
            for object in updated_objects:
                print(object)
            print(f"[DRY-RUN] {updated_objects_count} objects would have been UPDATED if this code actually ran")
        else:
            print(f"{updated_objects_count} objects in total were UPDATED")
    else:
        print(f"\nALL CLEAR: No Saved Objects needed to be updated!")
        print("")
    if duplicates:
        print("REVIEW DUPLICATE DATA VIEWS BEFORE REMOVING DUPLICATES WITH ZERO REFERENCES")
        for title, ids in duplicates.items():
            # Get the reference counts for each data view ID in the duplicated group
            reference_counts, all_objects = get_object_references(ids, kibana_url, space_id, object_types, headers)
            print(f"DATA VIEW TITLE: {title}")
            for id in ids:
                print(f"  ID: {id}  : {reference_counts[id]} references")
                dup_data_view_ids.append(id)
            print("")
    print("")
    if data_views_to_be_deleted:
        logging.warning("Data Views with the following IDs will be deleted:")
        print(f"List of Data Views to be deleted: {data_views_to_be_deleted}")
        try:
            data_views_to_be_deleted
        except NameError:
            print("")
            data_views_to_be_deleted = []
        for view_id in data_views_to_be_deleted:
            # Backup each data view
            backup_data_view(kibana_url, headers, space_id, view_id, f"Data_view_{view_id}_back_up.ndjson")

            # Check-in data views back-ups to Github
            dataview_local_file = f"data_view_{view_id}_backup.ndjson"
            dataview_repo_file_path = dataview_local_file
            upload_file_to_existing_github(repo_url, github_username, github_key, dataview_local_file, dataview_repo_file_path, github_branch, timestamp)

            # Delete each data view
            delete_dataview_if_no_references(view_id, all_objects, kibana_url, space_id, headers, dry_run)

    else:
        print("ALL CLEAR: No Data Views needed to be deleted!")
    # log_file_name = setup_log_file(timestamp)
    log_file = log_file_name
    log_repo_file_path = log_file
    upload_file_to_existing_github(repo_url, github_username, github_key, log_file, log_repo_file_path, github_branch, timestamp)


if __name__ == "__main__":
    parser = ArgumentParser(description='Automate the process of cleaning up duplicate data views!')
    parser.add_argument('--kibana_url', default='None', required=True)
    parser.add_argument('--api_key', default='None', required=True)
    parser.add_argument('--cluster_name', default='None', choices=['dev', 'qa', 'prod', 'ccs'], required=True)
    parser.add_argument('--space_id', default='None', required=True)
    parser.add_argument('--dry_run', choices=['True', 'False', 'false'], default='True')

    parser.add_argument('--github_username', default='None', required=False)
    parser.add_argument('--github_key', default='None', required=False)

    args = parser.parse_args()
    kibana_url = args.kibana_url
    api_key = args.api_key
    cluster_name = args.cluster_name
    space_id = args.space_id
    dry_run = args.dry_run

    github_username = args.github_username
    github_key = args.github_key


    if dry_run.lower() == 'true':
        dry_run = True
    else:
        dry_run = False

    # Get timestamp
    timestamp = set_timestamp()

    # MIGRATED: github.com replaces ghe.hedgeserv.net.
    # TODO: confirm the correct org/repo on github.com (e.g. hsv-internal) before running.
    repo_url = "https://github.com/oolajide_HSV/delete_duplicate_data_view"
    github_branch = f"{github_username}_{cluster_name}_{space_id}_{timestamp}"

    object_types = get_object_types()
    headers = get_headers(api_key)
    main(kibana_url, headers, space_id, dry_run)
