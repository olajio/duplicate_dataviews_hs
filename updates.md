Status record for the duplicate-data-view cleanup tooling. Originally a
forward-looking Jira-card breakdown; updated to reflect what was actually
decided and shipped. Grouped by change type, flagged per script. All items
below are **DONE** unless marked otherwise.

**Scope note**

- `delete_duplicate_data_view.py` — got both the GitHub migration and the Secrets Manager refactor.
- `find_duplicate_dataviews.py` and `get_spaces.py` — got the Secrets Manager refactor only (no GitHub code in either).
- Elasticsearch endpoint: not referenced anywhere. Every call goes through `kibana_url` (`/api/data_views`, `/api/saved_objects/*`, `/api/spaces/space`); there are no direct ES (9200/REST) calls, so no ES endpoint was added to the secrets.

**GitHub migration: ghe.hedgeserv.net → github.com (delete script only) — DONE**

- Replaced the hardcoded API base. GHE used `https://ghe.hedgeserv.net/api/v3`; github.com uses `https://api.github.com`. Handled by the new `parse_github_repo()` helper, which is host-agnostic (falls back to `<host>/api/v3` for any non-github.com host). Used by `upload_file_to_github` and `upload_file_to_existing_github`.
- Updated `repo_url` to `https://github.com/hsv-internal/delete_duplicate_data_view`. **Org `hsv-internal` confirmed and tested against the live repo.**
- Fixed the repo-owner/name parsing (was a hardcoded GHE host split) via `parse_github_repo()`.
- Switched auth from HTTP Basic (`auth=(github_username, github_key)`) to `Authorization: Bearer <PAT>` in `get_github_headers()`. `github_username` is now used only for the branch name, not auth.
- Added the recommended github.com REST headers: `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`.
- PAT: supplied by the service-account secret (see below). A fine-grained PAT scoped to the repo with Contents read/write is sufficient (create branch, create/update file).

**AWS Secrets Manager refactor (all three scripts) — DONE**

- Added `get_secret(secret_name, region)` to each script: boto3 `get_secret_value` via the default credential chain (IAM role / instance profile / IRSA — no inline creds). Returns the parsed JSON dict; secret values are never logged.
- Moved out of plaintext CLI args into secrets: `kibana_url`, the ES/Kibana API key, and the GitHub service-account credentials.
- **Secret layout (as actually built):**
  - Per-cluster: `elastic/kibana/dataview_cleanup_<cluster>` (one each for `dev`, `qa`, `prod`, `ccs`), keys `kibana_url` and `es_api_key`. Selected by `--cluster_name`.
  - GitHub: `github_hsv_internal/itsma/service_elastic_auto_HSV` (shared across clusters), keys `user` and `password`. `user` → branch name; `password` → Bearer PAT. Used only by the delete script.
  - Note: this differs from the original idea of co-locating a `github_pat`/`github_username` inside each cluster secret — the GitHub creds live in their own shared secret instead.
- **Region:** fixed at `us-east-2` in code (constant `AWS_REGION`); there is no `--region` argument.
- Argparse: removed `--api_key`, `--kibana_url`, `--github_username`, `--github_key`. Secret name is derived from `--cluster_name`. Kept `--space_id`, `--cluster_name` (delete + find), `--dry_run` (delete only), and added `--cluster_name` to `get_spaces.py`.
- Added `requirements.txt` (boto3, requests, pytz). IAM permission needed: `secretsmanager:GetSecretValue` on the five secret ARNs in `us-east-2`.
- Secrets kept out of logs: `get_secret` never logs values; `headers` are not logged.

**`--space_id all` (delete + find scripts) — DONE**

- Passing `--space_id all` lists every space in the cluster (`GET /api/spaces/space`) and runs against each; any other value runs against that single space.
- Delete script: no longer `sys.exit(0)`s the whole run on an empty space — it skips just that space so the rest still process, and each space gets its own per-run branch.

**Cleanups — DONE except where noted**

- `update_saved_object` `json.dumps` NameError — fixed (`json` imported).
- `get_response.text` typos (should be `response.text`) in `get_all_dataviews`, `retrieve_all_kibana_objects`, and `export_all_kibana_objects` — fixed (delete script + `find_duplicate_dataviews.py`; the export one was already correct in the migration_2 rewrite).
- `verify_ssl` arg to parametrize TLS verification — **NOT DONE (deferred).** Optional/consistency only; github.com and Elastic Cloud use public CAs so the hardcoded `verify=True` default stays on.

**Resolved decisions**

- GitHub backup/check-in behavior: **kept as-is.** Not moving to AWX; not shipping logs to Elasticsearch. The GitHub PAT stays in the service-account secret long-term.

**Testing**

- Real-environment testing completed against live AWS + Kibana + GitHub, including the bad-token negative test.

**Follow-up: preserve the space default data view (delete script) — DONE**

- Problem found in dev testing: a run deleted a duplicate that happened to be the space's default data view, leaving the space without a valid default.
- Fix: before deleting each duplicate, `reassign_default_if_deleting_default()` checks whether it is the current space default (`GET /s/<space>/api/data_views/default`). If so, it reassigns the default to the kept data view from the same title group (`POST .../data_views/default`, `force: true`) — only when the kept data view shares the same title, otherwise it logs and skips for safety. Dry-run aware (logs, no change). Non-default duplicates are unaffected.
- Added helpers `get_default_data_view_id()` and `set_default_data_view()`; `main()` now tracks `delete_to_keep` (deleted id -> kept id) and `id_to_title`.
- Docs updated: `README.md` (flowchart step + safeguard note) and the SharePoint runbook (`Cleanup Duplicate Data Views in Kibana Automation.md`).
