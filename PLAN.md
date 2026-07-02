# Dagster Integration Plan

Replace the single-repo MVP dagster sensor with a multi-repo loop driven by the
`repositories` table, so that every dataset linked to a GitHub repo gets a task
triggered when a PR merges to its configured branch.

---

## Assumptions

- GitHub credentials (`GH_TOKEN`, `GH_BASE_BRANCH`, etc.) are global env vars
the same for every repo (no per-repo creds in the DB).
- Trigger repo == delivery repo (same URI used to poll and to push results).
- Dagster talks to the webserver over HTTP (no direct DB access from dagster).

---

## Work items

### 1. Webserver ✅

- `Repository` model — `uri` (unique), `pr_cursor`, `base_branch`, `polled_at`, `datasets` backref
- `GET/POST/PATCH /repositories` endpoints + tests
- `Dataset.validate()` / `update()` — `repository` required, finds existing by URI, errors if not found
- Migration updated

---

### 2. `GithubAPI` / `GithubRepo` refactor + PR number cursor ✅

Replaced `GithubClient` with two classes in `dagster/app/github.py`:
- `GithubAPI` — HTTP + auth, takes an injected `requests.Session`
- `GithubRepo` — repo-specific operations, takes a `GithubAPI` instance

Added `get_merged_prs_after_number(pr_cursor, watch_dir)` to `GithubRepo`.
Filters by PR number client-side (sorted desc by created, stops when a page
contains only PRs at or below the cursor). 15/15 tests passing.

---

### 3. `GithubSensorConfig` — drop single-repo env vars

Remove `GH_OWNER` and `GH_REPO` from `_REQUIRED_VARIABLES` (and from the class).
Add `WEBSERVER_URL` to required vars so dagster knows where to call the repo API.

Keep global vars: `GH_TOKEN`, `GH_RESULTS_DIR`, `GH_WATCH_DIR`,
`GH_TRANSFER_DOCKER_IMAGE`.

Note: `GH_BASE_BRANCH` is the target branch for **results delivery PRs** — keep it
as a global env var. The **polling** base branch (what branch to watch for incoming
PRs) is now `base_branch` on the `Repository` model, defaulting to `main`.

---

### 4. `github_pull_request_polling_sensor` — multi-repo loop

Replace single-client poll with a loop over repos from the webserver API:

```
api = GithubAPI(token=gh_config.token)
repos = GET {webserver_url}/repositories
for repo in repos:
    parse owner/name from repo.uri
    gh_repo = GithubRepo(api, owner, name, repo.base_branch)
    new_prs = gh_repo.get_merged_prs_after_number(repo.pr_cursor, watch_dir)
    for pr in new_prs:
        yield RunRequest(
            run_key=f"{repo.id}-{pr.number}",
            tags={repo_id, repo_uri, pr_number, trigger=github}
        )
    if new_prs:
        PATCH {webserver_url}/repositories/{repo.id}  { pr_cursor: max, polled_at: now }
```

Dagster's own cursor is no longer used — state lives in the DB.

---

### 5. Replace `k8s_pipes_job` with `POST /tasks` + task monitoring

⚠️ **Scope changed** — see section 7 for full design notes.

Instead of Dagster running the analysis pod directly (K8s Pipes), Dagster should
call `POST /tasks` on the webserver so the task is tracked in the DB. The webserver
runs the pod. Dagster then monitors the task status and triggers results delivery.

`github_transfer_job` (K8s Pipes for results delivery to GitHub) is still needed
and is separate from task execution. It remains unchanged.

---

### 6. Tag propagation ✅ (partial)

`repo_id`, `repo_uri` forwarded in `github_run_success_transfer_sensor`.
Remaining: polling sensor (item 4) needs to set them on the initial RunRequest.

---

---

### 7. Task/webserver integration — replace `k8s_pipes_job` with `POST /tasks`

**The problem**: Currently Dagster's `github_pull_request_polling_sensor` yields a
`RunRequest` for `k8s_pipes_job`, which spins up a K8s pod directly via Dagster Pipes.
This bypasses the webserver entirely — no Task record is created, no audit trail, no
access to the results approval workflow.

**The goal**: When a GitHub PR arrives, Dagster should call `POST /tasks` on the
webserver so the task is tracked in the DB, then deliver results back via GitHub.

---

#### How `POST /tasks` works (key findings)

**Endpoint**: `POST /tasks` in `webserver/app/tasks_api.py:96`

**Minimal request body:**
```json
{
  "name": "experiment-name",
  "executors": [{ "image": "ghcr.io/org/experiment:latest", "env": {"KEY": "val"} }],
  "repository": "github.com/org/repo",
  "task_controller": true
}
```

**What the webserver does with it (`Task.validate` in `task.py:82`):**
1. Reads `executors[0]["image"]` → `docker_image`
2. Reads `repository` → looks up `Repository.uri` → finds the linked `Dataset` automatically
   (`task.py:104-109` — this path exists and works, it's how Dagster should resolve the dataset)
3. Reads `task_controller: true` → sets `is_from_controller = True` → skips CRD creation
   (`task.py:97,258` — CRD is the automatic results delivery system; we skip it so Dagster delivers)
4. Gets `requested_by` from Keycloak token in request headers
5. Creates `Task` record, calls `task.run()` which creates the K8s pod
6. Returns `{"task_id": <id>}`

**`task_controller: true` means**: "an external controller (Dagster) will handle results
delivery — don't create a CRD." The webserver still runs the pod normally.

**Note**: `task.run()` is **always** called — the webserver creates the K8s pod. Dagster
does NOT also spin up a pod. `k8s_pipes_job` should not be used for GitHub-triggered
tasks once this integration is in place.

---

#### PR spec JSON format — what the controller reveals

The task controller's `create_task_body()` (`crd.py:90`) shows exactly what `POST /tasks`
needs. For the GitHub PR spec JSON, the sensor forwards most fields directly:

```json
{
  "spec": {
    "name": "experiment-name",
    "executors": [{ "image": "ghcr.io/org/experiment:latest", "env": {"KEY": "val"} }],
    "inputs":  {},
    "outputs": {},
    "db_query": { "query": "SELECT ..." }
  }
}
```

Dagster adds `"repository": repo["uri"]` and `"task_controller": true` before posting.

**No `dataset_id`/`dataset_name` needed**: `Task.validate` checks `repository` first
(`task.py:104-109`). If a `Repository` record exists with that URI, the dataset is found
automatically — this is our path. No `project-name` header needed either (only required
for project-scoped tokens; system user bypasses it).

Only breaking change vs current: `docker_image` + `env` → `executors: [{image, env}]`.

---

#### Keycloak auth for Dagster — it's simpler than it looks

The task controller already solves this. It uses a dedicated controller user
(`KC_USER`) whose password is stored in k8s secret `controller-user-creds` under
`SYS_USER_PASS`. Auth flow (`keycloak_helper.py:get_fn_admin_token`):

```
POST {WEBSERVER_URL}/login   (form data: username=KC_USER, password=KC_PASSWORD)
  → {"token": "<refresh_token>"}
```

That refresh_token goes straight into `Authorization: Bearer <token>` on `POST /tasks`.
**No direct Keycloak calls needed.** The webserver's `/login` endpoint handles all
the Keycloak plumbing internally.

The controller user has `System` role in Keycloak, which causes the `@auth` wrapper
to skip the project check entirely (`wrappers.py:55` — admin/System role bypasses it).

**For Dagster, the env vars needed are just:**
```
WEBSERVER_URL       # already in GithubSensorConfig as of item 3
KC_USER             # the controller service account username
KC_PASSWORD         # its password (from k8s secret controller-user-creds / SYS_USER_PASS)
```

When `SKIP_USER_AUTH=true` on the controller, this is exactly the path used. Dagster
should do the same — no user impersonation, just the system user token.

---

#### What changes in Dagster

**`github_pull_request_polling_sensor`** (already rewritten in item 4):
- Currently reads `spec["docker_image"]` and yields `RunRequest` for `k8s_pipes_job`
- Change to: (1) call `POST /login` → get token, (2) call `POST /tasks` to create the
  task + start the pod, (3) yield `RunRequest` for a NEW `github_task_monitor_job` with
  `task_id` in tags

**New job: `github_task_monitor_job`** (replaces `k8s_pipes_job` in this flow):
- A Dagster op that polls `GET /tasks/{task_id}` until status == `terminated`
- On success, `github_run_success_transfer_sensor` picks it up (already exists) and
  triggers `github_transfer_job` — that sensor already forwards `repo_id`/`repo_uri`/`pr_number`

**`k8s_pipes_job`**: No longer used for GitHub-triggered tasks. Keep it — it's still
used as the `monitored_jobs` reference in `github_run_success_transfer_sensor`, and
`github_task_monitor_job` will replace it there.

**New env vars needed in Dagster (only 2 new ones):**
```
KC_USER         # controller service account username (same as task controller's KC_USER)
KC_PASSWORD     # its password (from k8s secret controller-user-creds / SYS_USER_PASS)
```
`WEBSERVER_URL` is already there from item 3. No Keycloak URL/realm/secret needed —
the webserver `/login` endpoint abstracts all of that.

---

#### How the controller does results delivery (push_to_github.sh)

The task controller delivers results by running a K8s helper job (`push_to_github.sh`):
1. Calls `GET /tasks/{id}/results` → gets a zip file
2. Clones the GitHub repo
3. Creates branch `{username}-{crd_name}-results`
4. Commits the zip into `results/{task_id}/`
5. Pushes and annotates the CRD as done

Dagster's `github_transfer_job` does the equivalent via K8s Pipes with a Docker image
(`GH_TRANSFER_DOCKER_IMAGE`). That image almost certainly wraps the same or similar
push logic. The key difference: Dagster's version is driven by `PARENT_RUN_ID` and
`PR_NUMBER` (Dagster run context) rather than CRD annotations.

**No change needed to `github_transfer_job`** — it's decoupled and works independently.

---

#### Target event flow (full picture)

```
GitHub PR merged
  → polling sensor detects PR
  → sensor: POST /login → token
  → sensor: POST /tasks {name, executors:[{image,env}], repository, task_controller:true}
      webserver creates Task record + K8s pod
  → sensor yields RunRequest for github_task_monitor_job
      tags: {task_id, pr_number, repo_id, repo_uri, trigger:github}
  → github_task_monitor_job polls GET /tasks/{task_id} until "terminated"
  → github_run_success_transfer_sensor triggers github_transfer_job
      (forwards pr_number, repo_uri from tags)
  → github_transfer_job (K8s Pipes) fetches results + pushes to GitHub
  → github_transfer_success_sensor triggers github_pr_comment_job
  → github_pr_comment_job adds comment to original PR
```

---

#### What is done ✅

- `github_task_monitor_op` + `github_task_monitor_job` — polls `GET /tasks/{id}` until terminated
- Polling sensor calls `POST /login` → `POST /tasks` → yields `RunRequest` for `github_task_monitor_job`
- `KC_USER`, `KC_PASSWORD` added to `GithubSensorConfig` + `_REQUIRED_VARIABLES`
- `github_run_success_transfer_sensor` now monitors `github_task_monitor_job`
- PR spec JSON format updated: `docker_image`+`env` → `executors: [{image, env}]`
- 28/28 tests passing

#### What is NOT yet done

- Update PR spec JSON format in real test repos (the experiment spec files in GitHub repos
  must be updated to use `executors: [{image, env}]` instead of `docker_image`+`env`)
- End-to-end smoke test in a real cluster

---

## File change summary

| File | Status |
|---|---|
| `webserver/app/repositories_api.py` | ✅ Done |
| `webserver/app/models/repository.py` | ✅ Done |
| `webserver/app/models/dataset.py` | ✅ Done |
| `webserver/app/__init__.py` | ✅ Done |
| `webserver/tests/test_repositories.py` | ✅ Done |
| `dagster/app/github.py` | ✅ Done — `GithubClient` + `GithubAPI` (uri-based) + `GithubRepo` |
| `dagster/app/tests/` | ✅ 28/28 tests passing |
| `dagster/app/definitions/sensors.py` | ✅ Items 3+4 done (config cleaned, polling sensor rewritten) |
| `dagster/app/definitions/sensors.py` | ✅ Item 7: `github_task_monitor_job`, `POST /tasks` integration, `KC_USER`/`KC_PASSWORD` |
