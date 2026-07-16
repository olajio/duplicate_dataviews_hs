Working notes for the GitHub migration + Secrets Manager refactor. Updated to
reflect the final, shipped state of the scripts (invocations here match the
current code).

**Logging destination — decided**

We considered ingesting the run logs into Elasticsearch (structured JSON docs +
ILM) instead of GitHub. **Decision: keep everything as-is.** The NDJSON object
backups and the text log file continue to be checked into the per-run GitHub
branch; we are not moving to AWX and not shipping logs to Elasticsearch. The
GitHub service-account PAT stays in Secrets Manager long-term.

**GitHub migration — what changed** (backup/check-in behavior preserved exactly)

- Added `parse_github_repo(repo_url)`: derives the REST API base and `owner/repo` from the repo URL. For `github.com` it returns `https://api.github.com`; for any other host (GHE) it falls back to `<host>/api/v3`. Host-agnostic, so the next host change won't touch the upload functions.
- Added `get_github_headers(github_key)`: `Authorization: Bearer <PAT>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.
- Reworked `upload_file_to_github` and `upload_file_to_existing_github` to use the helper's API base instead of the hardcoded GHE base, and switched from Basic auth to the Bearer header. `github_username` is used only for the branch name.
- `repo_url` is `https://github.com/hsv-internal/delete_duplicate_data_view` (org confirmed and tested).
- Added `from urllib.parse import urlparse`.

**Secrets Manager refactor — what changed**

- Credentials are no longer CLI args. `get_secret(secret_name, region)` (boto3, default credential chain) reads them from AWS Secrets Manager in `us-east-2`:
  - Kibana/ES per cluster: `elastic/kibana/dataview_cleanup_<cluster>` → `kibana_url`, `es_api_key` (selected by `--cluster_name`).
  - GitHub service account: `github_hsv_internal/itsma/service_elastic_auto_HSV` → `user` (branch name), `password` (Bearer PAT).
- Removed `--api_key`, `--kibana_url`, `--github_username`, `--github_key`. Region is fixed (`AWS_REGION = "us-east-2"`, no `--region`).
- `--space_id all` runs against every space in the cluster; each space gets its own branch.
- Default data view safeguard: before deleting a duplicate, if it is the space default the default is reassigned to the kept data view of the same title (`GET`/`POST /s/<space>/api/data_views/default`) before deletion; dry-run aware. Non-default duplicates unaffected.
- Fixed the `get_response.text` typos and the `json.dumps` NameError. `verify_ssl` arg intentionally not added.

Caveat still true: the existing-file upload doesn't pass a blob `sha`. Fine because each run uses a unique per-run branch and timestamped/ID-unique filenames, so paths never pre-exist. If a path ever repeats on the same branch, that PUT would 422 — inherited behavior, not a regression.

**Prerequisites to run**

- `pip install -r requirements.txt` (boto3, requests, pytz).
- AWS credentials available via the standard chain, allowed `secretsmanager:GetSecretValue` on the five secret ARNs in `us-east-2`.
- No GitHub PAT or Elastic API key on the command line — both come from the secrets above.

**Current invocation**

Single space, dry-run (default):
```
python3 delete_duplicate_data_view.py --cluster_name dev --space_id <space> --dry_run True
```

Every space in the cluster, applying changes:
```
python3 delete_duplicate_data_view.py --cluster_name prod --space_id all --dry_run False
```

Helpers:
```
python3 get_spaces.py --cluster_name <cluster>
python3 find_duplicate_dataviews.py --cluster_name <cluster> --space_id <space|all>
```

In dry-run, the full Kibana object export still happens and is pushed to GitHub
(only the data-view updates/deletes are simulated), so a dry-run still exercises
`upload_file_to_github` (new branch + `kibana_objects.ndjson`) and the end-of-run
log upload. Confirm the per-run branch (`<user>_<cluster>_<space>_<timestamp>`)
appears with both the NDJSON and `log_file_*.log`.

**Testing — completed**

Real-environment testing was completed against live AWS + Kibana + GitHub,
including the bad-token negative test (auth failures surface clearly rather than
silently no-op). Delete throwaway test branches once verified.
