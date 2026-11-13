# Code review: nexus/api/app and dagster/app

Read-only pass, 8 minute limit. Everything below was read in the code; nothing was run.
Line numbers marked `~` are within a few lines (read through offset windows).

## Bugs

### 1. Result `state`, `error` and `attempts` are writable on a final result
`nexus/api/app/results_api.py:231` (also `:150`)

- `step` goes through `set_step` -> `forward_only(RESULT_ORDER, ...)`, but `state` is assigned directly and has no table.
- So a PATCH without `step` always succeeds, even on a REVOKED / STALE / MERGED / CLOSED result.
- Concrete path: `dagster/app/delivery/results.py:~108` patches `state=IN_PROGRESS`, and the `except` at `:124` patches `state=FAILED, attempts+1, error=...`. If the result was revoked in between (results_api.py:147-152 does that), the success patch (has `step=PUSHED`) is refused with 409, then the except patch goes through and overwrites the `revoked: ...` error and bumps attempts on a final result.
- Suggested change: in `patch_result`, refuse any write when `result.step in FINAL_STEPS` (409, same as a refused move), or give `state` its own moves table next to `RESULT_ORDER` and call `transition`.

### 2. A pull request merged in the same second as the cursor is never ingested
`dagster/app/github.py:~67-71`, `dagster/app/gitea.py:~57-61`

- `get_pulls` stops at `updated_at <= since` and keeps only `merged_at > since`, both on whole seconds.
- The cursor is the latest stored merge time. If PR A is ingested and PR B then merges in that same second, B has `merged_at == since` and is dropped on every later poll.
- nexus-api already orders by the pair `(merged_at, number)` (`helpers/pull_request_fanout.py:~140`), the git clients do not.
- Suggested change: use `<` / `>=` in both clients. Re-posting an already stored PR is a no-op (`store_pull_request` uses `on_conflict_do_nothing`), but `PullRequestIngestSensor.ready` (`sensors/git/pr_ingest.py:~40`) would then need to ignore the PR that is the cursor itself, e.g. the backend returning the cursor number too.

### 3. Reconcile records the wrong start time
`dagster/app/definitions/sensors/task/run_status.py:~36-39`

- For a STARTED run, `task_fields` sets `started_at` to `now`. The reconcile sensor (`reconcile.py:~62`) uses the same function after the run-status sensors were down, so the task gets the time of the reconcile tick, not the run's start.
- Terminal statuses already read `record.start_time` from the run record.
- Suggested change: read the run record for STARTED as well and use `record.start_time`; drop `now`.

### 4. Ingest fetches everything before storing anything
`dagster/app/definitions/sensors/git/ingest_job.py:~42-49`

- All merged PRs and their file lists are fetched (2 calls per PR) and sorted before the first batch is posted. One failed call late in a large backlog fails the run with nothing stored, the cursor does not move, and each retry starts again from zero.
- Suggested change: sort `merged` by `(merged_at, number)` from the list response, then fetch and post one batch of `MAX_BATCH_SIZE` at a time.

### 5. The failure handlers can hide the real error
`dagster/app/delivery/results.py:124`, `dagster/app/definitions/sensors/task/pull_request_sync.py:111`

- Both `except Exception` blocks call `backend_api.patch_result` and then `raise`. If that patch fails (backend down, 409), its exception replaces the original one in the run's failure.
- In `results.py` the success patch is inside the same `try`, so a failed "PUSHED" patch after a good push is recorded as a failed delivery with `attempts+1`.
- Suggested change: move the success `patch_result` out of the `try` in both places, so the handler only covers the git work.

## Convention breaks

### 6. Retry bypasses the task moves table
`nexus/api/app/tasks_api.py:222-226`

- `retry_task` checks `RETRYABLE` and assigns `task.status = PENDING` directly; `TASK_MOVES` has no move back to PENDING, so the table does not describe all moves.
- Suggested change: add FAILED/CANCELED -> PENDING to a retry moves table (or a `RETRY_MOVES` dict) and call `transition`, which also gives the 409 the convention asks for (today it is `InvalidRequest` with the default status).

### 7. Dagster decides which deliveries are retried
`dagster/app/definitions/sensors/task/delivery.py:~93` and `dagster/app/delivery/results.py:~95`

- The retry sensor filters `result.step not in FINAL and result.attempts < DELIVERY_MAX_ATTEMPTS` itself, with its own copy of the final steps and its own max.
- `results.py` decides "just recorded, resource switched off" by comparing `result.error == SWITCHED_OFF_ERROR` and `attempts == 0`: a string shared between two codebases.
- Suggested change: have nexus-api answer this, e.g. a `retryable=true` filter on the results list, and a field on the create-result response for "held, switched off".

## Improvements

### 8. Three copies of backend pagination, one of them different
`dagster/app/backend.py:35-47`, `:83-115`, `:161-179`

- `get_projects` and `get_tasks` loop on `data["pages"]`; `get_pull_requests` uses `data.get("items", [])`, `isinstance(data, dict)` and `total`, defensive code the other two do not need.
- Suggested change: one `_paged(path, params)` generator using `data["pages"]`, used by all three.

### 9. Run-status sensors build their own backend client per event
`dagster/app/definitions/sensors/task/__init__.py:43-57`

- `_record_run_status` builds `BackendConfig` / `BackendAdapter` / `BackendSession` / `BackendAPI` by hand on every run status event, while every other sensor uses the `backend_api` resource.
- Suggested change: `required_resource_keys={"backend_api"}` on the five run-status sensors and pass `context.resources.backend_api`, as `delivery.py` does.

### 10. Gitea `get_file_contents` has a silent fallback
`dagster/app/gitea.py:~98-101`

- `if "content" in data: ... return data.get("content", "")` returns an empty string when the response has no content; GitHub's version indexes `data["content"]` and fails.
- Suggested change: copy the GitHub one-liner.

### 11. GitHub file listing makes one extra request per pull request
`dagster/app/github.py:~78-90`

- `get_pull_request_files` loops until an empty page, while `get_pulls` in the same class stops on a short page (`len(items) < GH_PAGE_SIZE`).
- Suggested change: same short-page stop, with a named page size.

### 12. Five identical run-status sensor definitions
`dagster/app/definitions/sensors/task/__init__.py:60-112`

- Queued/started/success/failure/canceled differ only in `run_status` and name.
- Suggested change: build them in a loop over the statuses.

## Checked and found fine

- `launch_task` (tasks_api.py:356-386): goes through `transition`, safe to repeat.
- `patch_task` (tasks_api.py:160-213): moves go through `TASK_MOVES`; run resources deleted before commit as documented.
- Launcher double launch: run key `task/<id>/<attempt>` de-duplicates.
- Delivery double launch: retry sensor checks in-flight runs by `fn/delivery_task_id`; first delivery keyed per task attempt.
- Duplicate results pull request: the sync sensor looks for an existing PR by head and base before opening one.
- `store_pull_request` / `create_triggers`: idempotent (conflict-do-nothing, savepoint per trigger).
- HTTP timeouts: set on the Dagster sessions (`utils.py`) and on nexus-api's outgoing calls I saw.
- `DbSessionMiddleware`: session removed per request.

## Not covered

- `nexus/api/app/helpers/keycloak.py` (1019 lines), `git_tokens.py`, `task_config.py`, `task_resources.py`, `kubernetes.py`, `soft_delete.py`.
- Routers: `projects_api.py`, `secrets_api.py`, `healthcheck_api.py`, `trigger_repositories_api.py`, `project_trigger_repositories_api.py`, `git_providers_api.py`, `users_api.py`, `dagster_api.py`, most of `datasets_api.py` and `results_api.py`.
- `nexus/api/app/models/` and `dtos/` (only `set_step` and the moves tables read), so no DTO or N+1 review.
- Dagster: `definitions/pipes.py`, `run_config.py`, `resources.py`, `delivery/git_push.py`, the push half of `delivery/results.py`, `pr_evaluate.py`, `evaluate_job.py`, `pr_parser.py`, `utils.py` retry adapter, `LaunchingSensor.run_key` / `run_in_flight`.
- How nexus-api computes `pr_cursor` (finding 2 relies on the docstring in `ingest_job.py`: "the latest stored merge").
