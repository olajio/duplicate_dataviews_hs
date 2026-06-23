Quick thought on the logging question first, then I'll do the migration.

Ingesting these logs into Elasticsearch is a sensible call, and arguably better than GitHub for the *logs* specifically (GitHub is fine for the NDJSON backups since those are recovery artifacts you may need to re-import, but logs are operational telemetry). A few things worth deciding when you get to that card: whether you write to a dedicated index like `.kibana-dataview-cleanup-logs` (or a non-dotted `dataview-cleanup-logs` with an ILM policy, since dotted/system-ish names can get awkward), whether you ship structured JSON docs per event rather than the flat text log (so you can actually query by `space_id`, `cluster_name`, `data_view_id`, `dry_run`, action taken, etc.), and whether you keep the GitHub log check-in too or fully replace it. I'd lean toward structured docs + ILM, and dropping the GitHub log upload once ES ingest is proven. But let's park that — it's its own card.

Let me do the GitHub migration now.The files came in as text rather than on disk, so I'll build the updated version from the content I have. Let me write it out with the migration applied.Parsing checks out for both hosts. Here's the migrated script.What changed (GitHub migration only — secrets refactor untouched, backup/check-in behavior preserved exactly):

- Added a `parse_github_repo(repo_url)` helper that derives the REST API base and `owner/repo` from the repo URL. For `github.com` it returns `https://api.github.com`; for any other host (GHE) it falls back to `<host>/api/v3`. This is host-agnostic so the next host change won't require touching the upload functions.
- Added a `get_github_headers(github_key)` helper returning the github.com token headers: `Authorization: Bearer <PAT>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.
- Reworked both `upload_file_to_github` and `upload_file_to_existing_github` to use the API base from the helper instead of the hardcoded `https://ghe.hedgeserv.net/api/v3`, and switched every call from Basic auth (`auth=(github_username, github_key)`) to the Bearer header. `github_username` is still passed in (it's used for the branch name in `main`) but no longer used for auth inside these functions.
- Updated the `repo_url` constant to `https://github.com/<ORG>/delete_duplicate_data_view` with a TODO — **you need to set the real org** (your `hsv-internal` org is the likely target for internal tooling, but confirm).
- Added `from urllib.parse import urlparse` to imports.

I deliberately did **not** touch the `json.dumps` NameError or the `get_response.text` typos, since those are out of scope for this card — flagging again so they don't surprise you mid-test (the `json` one will fire on a dry-run that finds objects to update).

One caveat to know going in: the existing-file upload still doesn't pass a blob `sha`. That's fine because each run uses a unique per-run branch and timestamped/ID-unique filenames, so paths never pre-exist on the branch. If a path ever repeats on the same branch, that PUT will 422 — not a regression, just inherited behavior.

**Testing steps for the migration**

Do these in order; the first few isolate GitHub from Kibana so you validate auth and repo access before a full run.

1. **Provision the PAT.** Create a fine-grained PAT scoped to the target repo with Contents: read/write (it needs to create branches and create/update files). Export it: `export GH_PAT='...'`.

2. **Smoke-test repo access (no script).** Confirm the base URL, token, and repo path all line up before involving the script:
   ```
   curl -sS -H "Authorization: Bearer $GH_PAT" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        https://api.github.com/repos/<ORG>/delete_duplicate_data_view | head
   ```
   A 200 with repo JSON means auth + repo path are correct. A 404 usually means the PAT can't see the repo (scope/org SSO) rather than a bad path.

3. **Unit-test the upload functions in isolation.** Import the two functions in a Python shell, point them at a throwaway file, and confirm a branch gets created and the file lands:
   ```
   python3 -c "
   from delete_duplicate_data_view import upload_file_to_github
   import os
   open('test.txt','w').write('migration smoke test')
   upload_file_to_github('https://github.com/<ORG>/delete_duplicate_data_view',
       'olajio', os.environ['GH_PAT'], 'test.txt', 'all_objects/test.txt',
       'migration-test-branch', '2026_06_23_test')
   "
   ```
   Expect: "Branch ... created successfully" then "File successfully uploaded". Verify in the GitHub UI that the branch and `all_objects/test.txt` exist. Then re-run with `upload_file_to_existing_github` against `migration-test-branch` to confirm the existing-branch path works too.

4. **Full dry-run against a low-stakes space.** Run the script with `--dry_run True` against dev and a space you don't mind branching:
   ```
   python3 delete_duplicate_data_view.py --kibana_url '<dev_kibana_url>' \
     --api_key '<es_api_key>' --cluster_name dev --space_id <space> \
     --dry_run True --github_username olajio --github_key "$GH_PAT"
   ```
   In dry-run, the full Kibana object export still happens and gets pushed to GitHub (only the data-view *updates/deletes* are simulated), so this exercises `upload_file_to_github` (new branch + `kibana_objects.ndjson`) and the end-of-run log upload via `upload_file_to_existing_github`. Confirm the per-run branch (`olajio_dev_<space>_<timestamp>`) appears with both the NDJSON and the `log_file_*.log`.

5. **Negative test — bad token.** Run step 2's curl with a garbage token and confirm you get a 401, so you know auth failures surface clearly rather than silently no-op.

6. **Cleanup.** Delete the throwaway `migration-test-branch` and any test run branches once verified.

If steps 2–4 pass, the migration is sound and you're clear to schedule the secrets-refactor card next. Want me to draft that secrets card now, or hold until you've run these?
