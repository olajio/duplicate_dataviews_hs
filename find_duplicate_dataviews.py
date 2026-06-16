import requests
import logging
from collections import defaultdict
from argparse import ArgumentParser



# dev_kibana_url = 'https://e001708f0fe44a4d96341be1bf9a9943.us-east-1.aws.found.io:9243'
# qa_kibana_url = 'https://66f6f47a3ef14711adcaa97b8385a6ed.us-east-1.aws.found.io:9243'
# prod_kibana_url = 'https://a8d089aa7eb241639d5ba3dbd343cd29.us-east-1.aws.found.io:9243'
# ccs_kibana_url = 'https://287d86a4b1184182b340bd5074cdfd7e.us-east-1.aws.found.io:9243'

# Initialize Kibana object types to be processed
def get_object_types():
    object_types = ["config", "config-global", "url", "index-pattern", "action", "query", "tag", "graph-workspace",
                    "alert", "search", "visualization", "event-annotation-group", "dashboard", "lens", "cases",
                    "metrics-data-source", "links", "canvas-element", "canvas-workpad", "osquery-saved-query",
                    "osquery-pack", "csp-rule-template", "map", "infrastructure-monitoring-log-view",
                    "threshold-explorer-view", "uptime-dynamic-settings", "synthetics-privates-locations",
                    "apm-indices", "infrastructure-ui-source", "inventory-view", "infra-custom-dashboards",
                    "metrics-explorer-view", "apm-service-group", "apm-custom-dashboards"]
    return object_types

# Set up headers for Kibana authentication
def get_headers(api_key):
    headers = {
        'kbn-xsrf': 'true',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {api_key}'
    }
    return headers


# Function to get all data views in the space ID specified
def get_all_dataviews(space_id, headers, kibana_url):
    dataview_url = f'{kibana_url}/s/{space_id}/api/data_views'
    response = requests.get(dataview_url, headers=headers, verify=True)
    if response.status_code == 200:
        response = response.json()
        data_views = response['data_view']
    else:
        logging.error(f"Failed to GET all Data Views . Status code: {response.status_code}, Response: : {get_response.text}")
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


# main
def main(kibana_url, headers, space_id):
    print(f"RUNNING THE SCRIPT FOR SPACE: '{space_id}' IN ELASTIC CLUSTER: '{cluster_name}'")
    data_views = get_all_dataviews(space_id, headers, kibana_url)
    duplicates = find_duplicated_data_views(data_views)
    print("")
    if not duplicates:
        print("ALL CLEAR: No duplicated Data views found.")
    else:
        dup_data_view_ids = []
        logging.warning("Duplicate data views found:")
        for title, ids in duplicates.items():
            # Get the reference counts for each data view ID in the duplicated group
            reference_counts, all_objects = get_object_references(ids, kibana_url, space_id, object_types, headers)
            print("")
            print(f"DATA VIEW TITLE: {title}")
            for id in ids:
                print(f"  ID: {id}  : {reference_counts[id]} references")
                dup_data_view_ids.append(id)

if __name__ == "__main__":
    parser = ArgumentParser(description='Automate the process of finding duplicate data views!')
    parser.add_argument('--kibana_url', default='None', required=True)
    parser.add_argument('--api_key', default='None', required=True)
    parser.add_argument('--cluster_name', default='None', choices=['dev', 'qa', 'prod', 'ccs'], required=True)
    parser.add_argument('--space_id', default='None', required=True)


    args = parser.parse_args()
    kibana_url = args.kibana_url
    api_key = args.api_key
    cluster_name = args.cluster_name
    space_id = args.space_id

    object_types = get_object_types()
    headers = get_headers(api_key)
    main(kibana_url, headers, space_id)
