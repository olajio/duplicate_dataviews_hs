# Cleanup Duplicate Data Views in Kibana Automation

> **Documentation on the automation for cleaning up duplicate data views in Kibana.**
>
> This page was updated to reflect the migration from GitHub Enterprise
> (`ghe.hedgeserv.net`) to `github.com`, and the move of all credentials
> (Kibana URL, Elastic API key, and GitHub service-account token) into
> **AWS Secrets Manager**. Credentials are no longer passed on the command line.

---

## Main components and relevant links

- **Code repo:** https://github.com/hsv-internal/delete_duplicate_data_view
- **The main script:** https://github.com/hsv-internal/delete_duplicate_data_view/blob/main/delete_duplicate_data_view.py
- **get_spaces script:** https://github.com/hsv-internal/delete_duplicate_data_view/blob/main/get_spaces.py
- **find_duplicate_dataviews script:** https://github.com/hsv-internal/delete_duplicate_data_view/blob/main/find_duplicate_dataviews.py — a read-only script that reports duplicate data views without changing anything.

---

## Requirements

- This is a Python script, so you need Python installed on your local machine, as well as any IDE of your choice that can run Python (e.g. PyCharm, VS Code).
- Ensure you have permission to install Python modules on your local machine. This is needed especially when running the script for the first time. Install the dependencies with:
  ```
  pip install -r requirements.txt
  ```
  (`requirements.txt` pins `boto3`, `requests`, and `pytz`.)

---

## Prerequisites

### AWS credentials (new)

The script now reads the Kibana URL, the Elastic API key, and the GitHub
service-account credentials from **AWS Secrets Manager** instead of taking them
as command-line arguments. Before running, make sure your shell has AWS
credentials available through the standard AWS credential chain (e.g. `aws sso
login`, `aws configure`, environment variables, or an assumed role).

The identity you use must be allowed to read the secrets in the **`us-east-2`**
region:

- IAM permission: `secretsmanager:GetSecretValue`
- On the secret ARNs listed in the [Secrets](#aws-secrets-manager-secrets) section below.

### Elastic API key

An Elastic API key is still required, but it is **stored inside the per-cluster
secret** (`es_api_key`) rather than passed on the command line. The key needs
permission to read, write (update), and delete Kibana objects (data views) in
every space in the deployment. The following API permission policy has been
tested to work well across all Kibana spaces:

```json
{
  "ELK-ITSMA-710-Role": {
    "cluster": ["all"],
    "indices": [
      {
        "names": ["*:*"],
        "privileges": ["all"],
        "field_security": { "grant": ["*"] },
        "allow_restricted_indices": true
      }
    ],
    "applications": [
      {
        "application": "kibana-.kibana",
        "privileges": [
          "feature_osquery.all",
          "feature_savedObjectsTagging.all",
          "feature_savedObjectsManagement.all",
          "feature_indexPatterns.all",
          "feature_advancedSettings.all",
          "feature_dev_tools.all",
          "feature_actions.all",
          "feature_stackAlerts.all",
          "feature_fleet.all",
          "feature_siem.all",
          "feature_logs.all",
          "feature_infrastructure.all",
          "feature_apm.all",
          "feature_uptime.all",
          "feature_observabilityCases.all",
          "feature_discover.all",
          "feature_dashboard.all",
          "feature_canvas.all",
          "feature_maps.all",
          "feature_ml.all",
          "feature_graph.all",
          "feature_visualize.all"
        ],
        "resources": ["space:*"]
      }
    ],
    "run_as": ["*"],
    "metadata": {},
    "transient_metadata": { "enabled": true }
  }
}
```

### GitHub Personal Access Token

You no longer create or supply your own PAT. The main script uploads the object
backups and log files to GitHub using a **service-account** credential stored in
Secrets Manager (`github_hsv_internal/itsma/service_elastic_auto_HSV`). The
`password` field of that secret is the token used as a Bearer PAT for the
`github.com` REST API, and the `user` field is used only to name the branch the
script creates.

### Space permission

In addition to the API key's permissions, the target space must also have the
necessary space permissions. Because the script uses the `data_view` and
`saved_objects` APIs, ensure the space has both **Data View Management** and
**Saved Objects Management** permissions.

---

## AWS Secrets Manager secrets

All secrets live in the **`us-east-2`** region. The region is fixed in the code
(there is no `--region` argument).

### Per-cluster Kibana/Elastic secret

The main script selects the secret to read based on `--cluster_name`:

| `--cluster_name` | Secret name |
| --- | --- |
| `ccs` | `elastic/kibana/dataview_cleanup_ccs` |
| `dev` | `elastic/kibana/dataview_cleanup_dev` |
| `qa` | `elastic/kibana/dataview_cleanup_qa` |
| `prod` | `elastic/kibana/dataview_cleanup_prod` |

Each of these secrets contains two keys:

- `kibana_url` — the Kibana URL for that cluster
- `es_api_key` — the Elastic API key described above

For reference, the `kibana_url` values stored in each cluster's secret are:

```
dev  = https://e001708f0fe44a4d96341be1bf9a9943.us-east-1.aws.found.io:9243
qa   = https://66f6f47a3ef14711adcaa97b8385a6ed.us-east-1.aws.found.io:9243
prod = https://a8d089aa7eb241639d5ba3dbd343cd29.us-east-1.aws.found.io:9243
ccs  = https://287d86a4b1184182b340bd5074cdfd7e.us-east-1.aws.found.io:9243
```

### GitHub service-account secret

- **Secret name:** `github_hsv_internal/itsma/service_elastic_auto_HSV`
- **Keys:**
  - `user` — the service-account username (used only to name the branch the script creates)
  - `password` — the token used as the Bearer PAT for the `github.com` REST API

This single secret is shared across clusters and is only used by the main
`delete_duplicate_data_view.py` script.

---

## Script parameters

The credential-related parameters (`--kibana_url`, `--api_key`,
`--github_username`, `--github_key`) have been **removed** — those values now
come from Secrets Manager. The remaining parameters are:

- `--cluster_name` — The cluster in which the target Kibana space resides. **Required.** This value both identifies the cluster and selects the Secrets Manager secret to read. Acceptable options: `dev`, `qa`, `prod`, `ccs`.
- `--space_id` — The ID of the target Kibana space where duplicate data views are to be cleaned up. **Required.** Note that a space's ID is often different from its display name — run `GET kbn:api/spaces/space`, or run `get_spaces.py`, to retrieve the correct ID.
  - **New:** pass the literal value `all` to run against **every space in the cluster**. When `--space_id all` is used, the script lists all spaces via `GET /api/spaces/space` and processes each one in turn.
- `--dry_run` — Optionally review what changes would be made without making them. Dry-run is applied to the functions that would change Kibana objects or delete data views. The script **defaults to dry-run**. Set `--dry_run "False"` to make actual changes. Accepted values: `True`, `False`, `false`.

> **Region note:** the AWS region is fixed at `us-east-2` in the code, so there
> is no region parameter to pass.

---

## Usage

### Main script — `delete_duplicate_data_view.py`

Command syntax:

```
python3 delete_duplicate_data_view.py --cluster_name "<cluster_name>" --space_id "<space_id>" --dry_run "True"
```

Sample command — single space, dry-run:

```
python3 delete_duplicate_data_view.py --cluster_name "dev" --space_id "test_space_ola" --dry_run "True"
```

Sample command — every space in the cluster, making actual changes:

```
python3 delete_duplicate_data_view.py --cluster_name "prod" --space_id "all" --dry_run "False"
```

### Helper — `get_spaces.py`

Lists all Kibana space IDs in the cluster (useful for finding the correct
`--space_id`):

```
python3 get_spaces.py --cluster_name "<cluster_name>"
```

### Helper — `find_duplicate_dataviews.py`

Reports duplicate data views (read-only; makes no changes). Also supports
`--space_id all`:

```
python3 find_duplicate_dataviews.py --cluster_name "<cluster_name>" --space_id "<space_id or all>"
```

---

## Restore Kibana objects and data views to original state

In the event that something goes wrong while updating Kibana objects or deleting
duplicate data views, the objects (lenses, visualizations, dashboards, maps,
data views, …) can be restored to their state prior to running the script.

- A file named `kibana_objects.ndjson` is created each time the script runs. This is the backup of **all** Kibana objects in the target space and should be used to restore all objects to their original state.
- Additionally, each data view is backed up right before it is deleted, in a file named `data_view_<data_view_id>_backup.ndjson` — for example, `data_view_2f0cb139-1d20-416c-9a50-27eb0f3420b2_backup.ndjson`.

These object backup files and the log file are also uploaded to the GitHub
branch that the script creates. The branch is named
`<user>_<cluster_name>_<space_id>_<timestamp>`, where `<user>` comes from the
GitHub service-account secret. **Taking note of the branch is important** in case
you later need to audit the run or restore objects from the backups. When
`--space_id all` is used, the script creates a **separate branch per space**.

---

## Expected results / validation

Once the script runs, it cleans up duplicated data views after updating the
objects that reference them to point at the ID of the "new"/"preferred" data
view. You can validate either manually in Kibana or by rerunning the script. On
a clean space, a rerun should report three **ALL CLEAR** messages:

- "No Duplicated Data views found"
- "No Saved Objects needed to be updated"
- "No Data Views needed to be deleted"

---

## How to use the script (BAU)

Running this script is considered a regular BAU operation, so no change request
is required. However, it is important to keep the ITSMA team in the loop when the
script is used to clean up a Kibana space. To do so, send an email with the
subject **"Cleanup Duplicate Data Views"** and share the link to the branch that
was created when the script ran.

The branch will contain the `kibana_objects.ndjson`, the `log_file_<timestamp>.log`,
and all the respective `data_view_<data_view_id>_backup.ndjson` files. The log
file can be used for forensics to audit the script's activities, and the
`kibana_objects.ndjson` and `data_view_<data_view_id>_backup.ndjson` files can be
used to restore all Kibana objects and the specifically deleted data views.
