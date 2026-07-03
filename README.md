# Kibana Duplicate Data View Cleanup

Automation for detecting and cleaning up **duplicate data views** (index
patterns) in Kibana. Duplicate data views — multiple index patterns sharing the
same title — cause data-quality and usability problems. This tooling finds the
duplicates, repoints every referencing Kibana object (searches, visualizations,
lenses, dashboards, maps, …) at a single preferred data view, backs everything
up, and then deletes the leftover duplicates that no longer have references.

All credentials are read from **AWS Secrets Manager** (region `us-east-2`) — no
API keys or tokens are passed on the command line.

---

## Scripts

| Script | Purpose | Changes Kibana? |
| --- | --- | --- |
| `delete_duplicate_data_view.py` | Full cleanup: repoint references, back up, and delete duplicate data views. Backs up all objects and logs to a per-run GitHub branch. | **Yes** (unless `--dry_run True`) |
| `find_duplicate_dataviews.py` | Report duplicate data views and their reference counts. Read-only. | No |
| `get_spaces.py` | List all Kibana space IDs in a cluster (to find the right `--space_id`). | No |

---

## Workflow (main script)

```
                 +--------------------------------------+
                 |  START: parse CLI args               |
                 |  --cluster_name  --space_id          |
                 |  --dry_run (default True)            |
                 +------------------+-------------------+
                                    |
                                    v
                 +--------------------------------------+
                 |  Read AWS Secrets Manager (us-east-2)|
                 |  elastic/kibana/dataview_cleanup_<c> |
                 |      -> kibana_url, es_api_key       |
                 |  github_hsv_internal/itsma/          |
                 |  service_elastic_auto_HSV            |
                 |      -> user, password (PAT)         |
                 +------------------+-------------------+
                                    |
                                    v
                 +--------------------------------------+
                 |  Is --space_id == "all" ?            |
                 +--------+--------------------+--------+
                          | yes                | no
                          v                    v
          +-----------------------+   +--------------------+
          | GET /api/spaces/space |   | use the single     |
          | -> list ALL spaces    |   | space_id given     |
          +-----------+-----------+   +---------+----------+
                      |                         |
                      +------------+------------+
                                   |
                                   v
        +=========================================================+
        ||  FOR EACH SPACE:                                      ||
        |+=======================================================+|
        ||                                                       ||
        ||   +-----------------------------------------------+   ||
        ||   | Retrieve ALL Kibana objects in the space      |   ||
        ||   +----------------------+------------------------+   ||
        ||                          |                            ||
        ||                          v                            ||
        ||                +-------------------+                  ||
        ||                | 0 objects found?  |--- yes --> skip  ||
        ||                +---------+---------+          (next   ||
        ||                          | no                  space) ||
        ||                          v                            ||
        ||   +-----------------------------------------------+   ||
        ||   | Export all objects -> kibana_objects.ndjson   |   ||
        ||   | Create per-run branch and upload the backup   |   ||
        ||   | to GitHub (hsv-internal/delete_duplicate_...) |   ||
        ||   +----------------------+------------------------+   ||
        ||                          |                            ||
        ||                          v                            ||
        ||   +-----------------------------------------------+   ||
        ||   | Get data views; group by title to find        |  ||
        ||   | duplicates                                    |   ||
        ||   +----------------------+------------------------+   ||
        ||                          |                            ||
        ||                          v                            ||
        ||                +-------------------+                  ||
        ||                | duplicates found? |-- no --> ALL     ||
        ||                +---------+---------+          CLEAR   ||
        ||                          | yes                        ||
        ||                          v                            ||
        ||   +-----------------------------------------------+   ||
        ||   | For each duplicate group (same title):        |   ||
        ||   |   - count references per data view            |   ||
        ||   |   - KEEP the most-referenced data view        |   ||
        ||   |   - repoint referencing objects at the kept   |   ||
        ||   |     data view          [simulated in dry-run] |   ||
        ||   +----------------------+------------------------+   ||
        ||                          |                            ||
        ||                          v                            ||
        ||   +-----------------------------------------------+   ||
        ||   | For each leftover duplicate:                  |   ||
        ||   |   - backup -> data_view_<id>_backup.ndjson    |   ||
        ||   |   - upload backup to the GitHub branch        |   ||
        ||   |   - if no references remain: prompt Y/N,      |   ||
        ||   |     then DELETE        [simulated in dry-run] |   ||
        ||   +----------------------+------------------------+   ||
        ||                          |                            ||
        ||                          v                            ||
        ||   +-----------------------------------------------+   ||
        ||   | Upload log_file_<timestamp>.log to the branch |   ||
        ||   +----------------------+------------------------+   ||
        ||                          |                            ||
        |+--------------------------+----------------------------+|
        +=========================================================+
                                   |
                                   v
                                 +-----+
                                 | END |
                                 +-----+
```

> In **dry-run** (the default), the object export and all GitHub uploads still
> happen — only the data-view *updates* and *deletes* are simulated. This lets
> you review exactly what would change while still producing the backups.

---

## Prerequisites

- **Python 3** and the dependencies in `requirements.txt`:
  ```
  pip install -r requirements.txt
  ```
- **AWS credentials** available through the standard credential chain (`aws sso
  login`, `aws configure`, environment variables, or an assumed role), allowed:
  - `secretsmanager:GetSecretValue` on the secret ARNs below, in region `us-east-2`.
- **Elastic API key** (stored in the per-cluster secret) with permission to read,
  update, and delete Kibana objects in every space in the deployment.
- **Space permissions:** the target space needs both **Data View Management** and
  **Saved Objects Management** enabled.

### AWS Secrets Manager layout (region `us-east-2`)

Per-cluster secret, selected by `--cluster_name`:

| `--cluster_name` | Secret name | Keys |
| --- | --- | --- |
| `ccs` | `elastic/kibana/dataview_cleanup_ccs` | `kibana_url`, `es_api_key` |
| `dev` | `elastic/kibana/dataview_cleanup_dev` | `kibana_url`, `es_api_key` |
| `qa` | `elastic/kibana/dataview_cleanup_qa` | `kibana_url`, `es_api_key` |
| `prod` | `elastic/kibana/dataview_cleanup_prod` | `kibana_url`, `es_api_key` |

GitHub service-account secret (shared; used only by the main script):

| Secret name | Keys |
| --- | --- |
| `github_hsv_internal/itsma/service_elastic_auto_HSV` | `user` (branch name), `password` (Bearer PAT) |

---

## Usage

The region is fixed at `us-east-2` in code, so there is no `--region` argument.

### `delete_duplicate_data_view.py`

| Argument | Required | Notes |
| --- | --- | --- |
| `--cluster_name` | yes | `dev` \| `qa` \| `prod` \| `ccs`. Also selects the secret. |
| `--space_id` | yes | A space ID, or `all` to run against every space in the cluster. |
| `--dry_run` | no | `True` (default) \| `False`. Set `False` to make actual changes. |

```
# Single space, dry-run (default) — safe preview
python3 delete_duplicate_data_view.py --cluster_name dev --space_id <space_id> --dry_run True

# Every space in the cluster, applying changes
python3 delete_duplicate_data_view.py --cluster_name prod --space_id all --dry_run False
```

### `find_duplicate_dataviews.py`

```
python3 find_duplicate_dataviews.py --cluster_name <cluster> --space_id <space_id|all>
```

### `get_spaces.py`

```
python3 get_spaces.py --cluster_name <cluster>
```

> Tip: a space's **ID** is often different from its display name. Use
> `get_spaces.py` (or `GET kbn:api/spaces/space`) to find the correct
> `--space_id`.

---

## Outputs, backups, and restore

Each run creates a GitHub branch named `<user>_<cluster>_<space_id>_<timestamp>`
(with `--space_id all`, one branch per space) and uploads:

- `kibana_objects.ndjson` — backup of **all** Kibana objects in the space.
- `data_view_<data_view_id>_backup.ndjson` — one per data view, taken just before deletion.
- `log_file_<timestamp>.log` — the full run log (for audit/forensics).

To restore, re-import the relevant `.ndjson` file(s) via Kibana's Saved Objects
import. **Note the branch name** for any run so the backups can be found later.

---

## Validation

After a cleanup, rerun the script against the same space. A clean space reports
three **ALL CLEAR** messages:

- "No Duplicated Data views found"
- "No Saved Objects needed to be updated"
- "No Data Views needed to be deleted"

---

## Notes

- Running this is a regular BAU operation (no change request required), but keep
  the ITSMA team in the loop: email the subject **"Cleanup Duplicate Data Views"**
  with a link to the run's branch.
- Full runbook: **`Cleanup Duplicate Data Views in Kibana Automation.md`**.
