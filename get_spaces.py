import requests
from argparse import ArgumentParser


def get_headers(api_key):
    headers = {
        'kbn-xsrf': 'true',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {api_key}'
    }
    return headers

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
    parser.add_argument('--kibana_url', default='None', required=True)
    parser.add_argument('--api_key', default='None', required=True)

    args = parser.parse_args()
    kibana_url = args.kibana_url
    api_key = args.api_key

    headers = get_headers(api_key)

    space_ids = list_kibana_space_ids(headers, kibana_url)
    print(f"Kibana Space IDs: \n")
    for space in space_ids:
        print(f" {space}")
