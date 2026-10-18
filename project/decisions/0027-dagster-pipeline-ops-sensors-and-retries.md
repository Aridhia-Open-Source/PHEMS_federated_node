# 0027. The Dagster pipeline: ingest as an op, thin sensors, and retries

- Status: Accepted (built). Replaces section 4 of [0019](0019-global-resources-and-shared-pull-requests.md). Amends [0017](0017-task-status-written-by-run-status-sensors.md) (the launcher does patch a task, to `FAILED`, see below) and the run-key part of [0009](0009-sync-reconciler-and-operational-rules.md).

## Context

Before this change the sensors did the work inside the tick: they polled the provider, fetched files and wrote to the backend, so a slow or broken repository stalled or failed the whole tick. Pull requests are now stored once per global trigger repository ([0023](0023-pull-requests-stored-once-fan-out-and-cursors.md)) and a task is pinned to its configuration ([0024](0024-task-configuration-pinning.md)). The pipeline needed a shape where the slow work runs as a run (visible, retryable) and the sensors only decide what to launch.

## Decision

**Ingest is an op.** `ingest_pull_requests` (`dagster/app/definitions/sensors/git/ingest_job.py`) runs in `ingest_pull_requests_job` with config `repo_id`.
- It re-reads the repository for its current `pr_cursor`, lists merged pull requests since it, fetches each one's files, and sorts them oldest first by `(merged_at, number)`.
- It posts them in batches of at most `MAX_BATCH_SIZE = 100` to `POST /global/repositories/triggers/<id>/pull_requests` (`BackendAPI.create_pull_requests_batch`, which refuses more than 100). The cursor moves only when a batch is stored, so a failed batch leaves nothing older unposted behind a newer one.
- Duplicate file paths are dropped before the post, because the backend would 500 the whole batch.

**The ingest sensor** (`PullRequestIngestSensor`, `git/pr_ingest.py`) launches one run per pollable repository: `GET /global/repositories/triggers?pollable=true` (enabled repository, provider and secret; project links are ignored). It is "thin" in that it only decides: `ready()` still makes one provider call per repository to see whether anything merged since the cursor.

**One base class for the git and delivery-retry sensors.** `LaunchingSensor` (`definitions/sensors/base.py`): per item, skip it if a run with its tags is in flight, check it, yield a `RunRequest`. A failing item is logged and the others still launch; the tick fails, naming the items, only when nothing launched. This is how one failing repository does not stop the others.

**The evaluate sensor** (`PullRequestEvaluateSensor`, `git/pr_evaluate.py`) loops over projects `?enabled=true&locked=false`, their links `?active=true`, and a link's pull requests `?state=UNKNOWN`. Every filter is a query option on the webserver; Dagster does not fetch lists and filter them. It launches `evaluate_repository_pull_requests_job`, which maps `evaluate_pull_request` over the `UNKNOWN` pull requests (3 at a time, op retry policy 3 retries with exponential backoff).
- `record_outcome` posts the spec to `.../pull_requests/<n>/task`. A 400 is logged (the backend rejected the spec and recorded why). A 409 (no longer `UNKNOWN`, or the link is inactive) is treated as skip. Anything else raises.
- The webserver owns the match rule. `spec_files` (`webserver/app/helpers/spec_files.py`: files the pull request adds, ending in `.json`, under `watch_dir`) decides fan-out and is exposed on the trigger as `spec_files`. Dagster's `PullRequestParser` (`git/pr_parser.py`) trusts it: none gives `REJECTED`, several gives `REJECTED`, one is read at the merge commit.

**The launcher** (`TaskLauncherSensor`, `task/launcher.py`) lists `PENDING` tasks of `?enabled=true` projects.
- Launch gate: `GET /projects/<pid>/tasks/<id>/config` ([0024](0024-task-configuration-pinning.md)). If the configuration is not current, or the dataset link is not active, or the dataset's secret is disabled, the launcher patches the task `FAILED` with the cause (`state_cause`, cut at 1024 characters for the configuration case) and moves on.
- Any other error (a failing GET) leaves the task `PENDING`, is logged, and is retried next tick; its run key was never used. One bad task never stops the rest.
- Run key `task/<id>/<attempt>`, tags `trigger=task`, `task_id`, `attempt`, `project_id`, `project`.

**Run-status sensors write the task status** ([0017](0017-task-status-written-by-run-status-sensors.md)). Five (`task_queued_sensor`, `task_started_sensor`, `task_success_sensor`, `task_failure_sensor`, `task_canceled_sensor` in `task/__init__.py`) act only on runs tagged `trigger=task` and patch `status` and `executor_run_id` (`TaskRunStatusSensor`, `task/run_status.py`). A 409 (task already final) is logged and skipped. `executor_run_id` replaced `dagster_run_id` (`tasks.executor_run_id`, unique). The launcher's `FAILED` is the one other writer, for rule failures where no run exists ([0026](0026-state-transition-tables.md) lists the allowed moves).

**Delivery** (`task/delivery.py`, `app/delivery/results.py`).
- `task_results_delivery_sensor` is a sixth run-status sensor: on `SUCCESS` of a task run it requests `deliver_results_job` (key `deliver/<task>/<attempt>`, tags `trigger=delivery`, `delivery_task_id`, never `task_id`).
- `ResultsDelivery` reads where to deliver from the task's pinned `config_snapshot` (`results.repository_id`, `target_dir`), not from the project's link. It posts the result, pushes a branch (zip, `spec.json`, `metadata.json`), records `PUSHED`, opens the pull request, then records `OPENED` with state `DELIVERED`. It resumes from the step reached: an existing branch is not pushed again and an existing pull request is reused. It never touches the task status.
- `results_delivery_retry_sensor` relaunches results with state `FAILED` on an active link (`?state=FAILED&active_link=true`), step not final, and `attempts < DAGSTER_DELIVERY_MAX_ATTEMPTS`.
- `results_pull_request_sync_sensor` launches `sync_results_pull_requests_job` when results are `PUSHED` or `OPENED` and no sync is in flight. It records the provider's `MERGED`/`CLOSED`; a 404 on the provider is skipped, not guessed.

**Shared settings** (`dagster/app/config.py`, chart `k8s/federated-node/values.yaml` under `fnDagster.sensors`):
- `minIntervalSeconds` (30; `DAGSTER_SENSORS_MIN_INTERVAL_SECONDS`): one value for all 11 sensors.
- `retryIntervalSeconds` (60): `run_key(kind, item, state)` ends in `slot = time // retryInterval`, so a failed run with unchanged input is retried once per interval. Run keys are permanent in Dagster, so without the slot a failed run would never be relaunched. Launcher and first delivery keep keys without a slot (exactly once per attempt).
- `deliveryMaxAttempts` (5): then the result stays `FAILED` until relaunched by hand.
- `initialStatus` (`STOPPED`): every sensor defaults to `STOPPED`.

**The 11 sensors:** `git_pull_request_ingest_sensor`, `git_pull_request_evaluate_sensor`, `task_launcher_sensor`, the five run-status sensors above, `task_results_delivery_sensor`, `results_delivery_retry_sensor`, `results_pull_request_sync_sensor`.

**Start order.** fncli starts them (`fncli start-sensor --sensor all`, `dagster/fncli/cmds/sensor.py`): the five run-status sensors and the delivery sensor first, the launcher last, because run-status sensors only see events from when they start and a run that finishes first would leave its task `PENDING` for good.

**Test image.** `pypipes/main.py` is the reference task image. With `PYPIPES_EXIT_CODE` set it exits with that code before doing anything; `fncli open-pr --kind failing` sets it to produce a task that fails.

## Consequences

- A failing repository, pull request or task costs one run or one log line, not a tick.
- Retrying is bounded by time (one slot) and, for delivery, by attempts; nothing retries faster than the retry interval.
- Every sensor adds a webserver call per project per tick (evaluate: one list per project, plus one per link).
- A task's status is still a mirror of its run except for the launcher's rule failures.

## Alternatives considered

- **Do the ingest in the sensor tick** (the old way): rejected, one repository fails the tick and nothing is visible in the run list.
- **Launcher marks the task `QUEUED`**: rejected in 0017, it races the run-status sensor. It marks `FAILED` only when no run will exist.
- **Dagster filters lists in Python**: rejected; filters are webserver query options (`pollable`, `enabled`, `locked`, `active`, `state`, `active_link`).
- **A per-sensor interval**: rejected for one chart value.

## Where it lives

- PR #557, branch `split/03-dagster`: `dagster/app/definitions/` (`sensors/base.py`, `sensors/git/`, `sensors/task/`, `jobs.py`, `run_config.py`), `dagster/app/delivery/`, `dagster/app/backend.py`, `dagster/app/config.py`, `pypipes/`.
- Chart: `k8s/federated-node/values.yaml` (`fnDagster.sensors`), `templates/dagster-env-config.yaml`. fncli: `dagster/fncli/cmds/sensor.py`.
- Webserver side: `webserver/app/helpers/spec_files.py`, `trigger_repositories_api.py` (`pollable`, batch limit), `tasks_api.py`.

## Not built or open

- `POST /tasks/<id>/cancel` is not implemented; the exit code is not recorded by the run-status sensors (`exit_code` exists on the task but nothing sets it).
- The launcher filters only `enabled`, not `locked`: a locked project's `PENDING` tasks still launch. 0019 says locked pauses launch; the launcher pauses nothing for a lock; only the evaluate sensor (`locked=false`) and `POST /projects/<id>/tasks` (`tasks_api.py`, 409) respect it.
- `docs/architecture/flows.md` says the loop runs "every 10 s"; the default is 30 s (2 s in `k8s/federated-node/dev.example.values.yml`).
- A delivery stays `FAILED` after `deliveryMaxAttempts` with no alert.
- Open: should the ingest sensor stop calling the provider and leave that to the op, so the sensor is thin in fact?
