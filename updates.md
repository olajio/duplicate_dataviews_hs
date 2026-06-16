Looked through all three. Here's the breakdown you can drop into a Jira card. I've grouped it by change type and flagged which script each item applies to, since the GitHub work only lives in `delete_duplicate_data_view.py` while the secrets work touches all three.

**Scope note up front**

- `delete_duplicate_data_view.py` — needs both the GitHub migration and the Secrets Manager refactor.
- `find_duplicate_dataviews.py` and `get_spaces.py` — only need the Secrets Manager refactor (no GitHub code in either).
- Elasticsearch endpoint: not currently referenced anywhere. Every call goes through `kibana_url` (`/api/data_views`, `/api/saved_objects/*`, `/api/spaces/space`). There are no direct ES (9200/REST) calls, so there's nothing to wire an ES endpoint into today. Recommend leaving it out of the secret unless a future direct-ES call is planned, then add it as an unused-for-now field.

**GitHub migration: ghe.hedgeserv.net → github.com (delete script only)**

- Replace the hardcoded API base. GHE used `https://ghe.hedgeserv.net/api/v3`; github.com uses `https://api.github.com` (note: it is NOT `https://github.com/api/v3`). This affects `upload_file_to_github` and `upload_file_to_existing_github`.
- Update `repo_url` constant from `https://ghe.hedgeserv.net/ITSMA/delete_duplicate_data_view` to the new `https://github.com/<org>/<repo>` location.
- Fix the repo-owner/name parsing. Both functions do `repo_url.split("https://ghe.hedgeserv.net/")[1]`, which is hardcoded to the GHE host. Switch to splitting on `https://github.com/` (or parse owner/repo more robustly so a host change doesn't break it again).
- Switch authentication from HTTP Basic to token header. Current calls use `auth=(github_username, github_key)`. On github.com, move to `Authorization: Bearer <PAT>` (or `token <PAT>`) in headers. `github_username` is then only needed for the branch name (`{username}_{cluster}_{space}_{timestamp}`), not for auth.
- Add recommended github.com REST headers: `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`.
- Confirm PAT type/scope on the new secret: a fine-grained PAT scoped to the single repo with Contents read/write is sufficient (create branch, create/update file). Document which PAT type the card expects.

**AWS Secrets Manager refactor (all three scripts)**

- Add boto3 retrieval (Secrets Manager `get_secret_value`) using the default credential chain (IAM role / instance profile / IRSA — no inline creds), consistent with the existing AWX-based pattern.
- Move these out of plaintext CLI args / config into the secret: ES/Kibana API key (`--api_key`), `kibana_url`, and the GitHub PAT (`--github_key`).
- Decide on `github_username`: not strictly sensitive, but co-locating it in the same secret keeps the call signature clean. Note this either way in the card.
- Secret layout: one JSON secret per cluster, secret name = deployment/cluster name (matches the established `secret name == deployment name` convention), with fields like `kibana_url`, `es_api_key`, `github_pat`, and optionally `github_username`.
- Replace `--api_key`, `--kibana_url`, `--github_key` argparse args with a secret reference plus region (e.g. `--secret_name` / `--region`, or derive secret name from `--cluster_name`). Keep `--space_id`, `--cluster_name`, and `--dry_run`.
- Add a dependency on boto3 and document the IAM permission needed (`secretsmanager:GetSecretValue` on the specific secret ARNs).
- Ensure secrets never hit logs: don't log `headers` (contains the API key) and keep the GitHub PAT out of any debug output.

**Worth fixing while the refactor is open (low-priority, optional)**

- `update_saved_object` calls `json.dumps(payload)` in the dry-run branch but `json` is never imported → NameError the moment a dry-run update fires. The Secrets Manager work doesn't touch this, but it's a latent crash in the same file.
- Several error branches reference an undefined `get_response.text` (should be `response.text`) in `get_all_dataviews`, `retrieve_all_kibana_objects`, and `export_all_kibana_objects` → these raise NameError instead of logging the real error. Cheap to fix while in the file.
- Optional, to match your other AWX-refactored scripts: parametrize TLS verification via a `verify_ssl` survey arg rather than the hardcoded `verify=True`. github.com and Elastic Cloud both use public CAs so the default should stay on; this is purely for consistency.

One thing to decide before writing the card: do you want the GitHub backup/check-in behavior kept as-is in the delete script, or is the eventual target to run this under AWX where the NDJSON backups and logs might go somewhere else? That choice affects whether the GitHub PAT even belongs in the secret long-term.
