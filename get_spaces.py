import json
import requests
from argparse import ArgumentParser
import boto3
from botocore.exceptions import ClientError


# AWS region where all the Secrets Manager secrets live.
AWS_REGION = "us-east-2"


def get_headers(api_key):
    headers = {
        'kbn-xsrf': 'true',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {api_key}'
    }
    return headers


# Retrieve a JSON secret from AWS Secrets Manager using the default credential
# chain (IAM role / instance profile / IRSA — no inline credentials). Returns
# the parsed secret as a dict. Secret values are never logged.
def get_secret(secret_name, region_name):
    client = boto3.session.Session().client(
        service_name="secretsmanager", region_name=region_name
    )
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        print(f"Failed to retrieve secret '{secret_name}' from AWS Secrets Manager "
              f"in region '{region_name}': {e}")
        raise
    return json.loads(response["SecretString"])

def list_kibana_space_ids(headers, kibana_url):
    """Fetch all Kibana spaces and list only the space IDs."""
    kibana_space_url = f"{kibana_url}/api/spaces/space"

    try:
        # Send the GET request to the Kibana API
        response = requests.get(kibana_space_url, headers=headers, verify=True)
        response.raise_for_status()

        # Parse the response JSON
        spaces = response.json()

        # Extract and return the space IDs
        space_ids = [space["id"] for space in spaces]
        return space_ids

    except requests.exceptions.RequestException as e:
        print(f"Error fetching Kibana spaces: {e}")
        return []

# Example usage
if __name__ == "__main__":
    parser = ArgumentParser(description='Automate the process of cleaning up duplicate data views!')
    parser.add_argument('--cluster_name', default='None', choices=['dev', 'qa', 'prod', 'ccs'], required=True)

    args = parser.parse_args()
    cluster_name = args.cluster_name

    # Retrieve Kibana/ES credentials from AWS Secrets Manager. The secret to use
    # is selected by --cluster_name: 'elastic/kibana/dataview_cleanup_<cluster>'
    # (e.g. --cluster_name qa -> 'elastic/kibana/dataview_cleanup_qa'), each
    # holding 'kibana_url' and 'es_api_key'.
    kibana_secret_name = f"elastic/kibana/dataview_cleanup_{cluster_name}"
    kibana_secret = get_secret(kibana_secret_name, AWS_REGION)
    kibana_url = kibana_secret["kibana_url"]
    api_key = kibana_secret["es_api_key"]

    headers = get_headers(api_key)

    space_ids = list_kibana_space_ids(headers, kibana_url)
    print(f"Kibana Space IDs: \n")
    for space in space_ids:
        print(f" {space}")
