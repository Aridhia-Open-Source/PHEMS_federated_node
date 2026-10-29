# 0014. The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries

## Context

Pull requests are stored once per global repository ([0011](0011-pull-requests-stored-once-fan-out-and-cursors.md)), so the pipeline has to poll once per repository and keep one failing repository, pull request or task from stalling the rest. Slow work should run as a visible Dagster run, and the sensors should mostly decide what to launch.

## Decision

**Twelve sensors** (`dagster/app/definitions/sensors/`), 2 in `git/` and 10 in `task/`:
- `git_pull_request_ingest_sensor`, `git_pull_request_evaluate_sensor`
- `task_launcher_sensor`
- five run-status sensors on `k8s_pipes_job`: `task_queued_sensor`, `task_started_sensor`, `task_success_sensor`, `task_failure_sensor`, `task_canceled_sensor`
- `task_reconcile_sensor`: every tick it reads the current status of the run of each unfinished task and patches the task when it differs, so a missed run-status event is repaired
- `task_results_delivery_sensor` (a run-status sensor too: on a task run's `SUCCESS` it requests `deliver_results_job`)
- `results_delivery_retry_sensor`, `results_pull_request_sync_sensor`

**Ingest is an op.** The ingest sensor launches one `ingest_pull_requests_job` run per pollable repository (`GET /global/repositories/triggers?pollable=true`: repository, provider and secret enabled, project resources ignored). Its `ready()` still asks the provider whether anything merged since the cursor. The op `ingest_pull_requests` re-reads the repository for its current cursor, fetches the merged pull requests and their files ([0012](0012-github-ingest-pulls-endpoint.md)), sorts them by `(merged_at, number)` and posts them in batches of at most 100 (`MAX_BATCH_SIZE`; `BackendAPI.create_pull_requests_batch` refuses more). The cursor only moves when a batch is stored, so a failed batch never leaves an older pull request unposted behind a newer one. Duplicate file paths are dropped before the post.

**Per-repository isolation.** The ingest, evaluate and delivery-retry sensors share `LaunchingSensor` (`sensors/base.py`): per item, skip it if a run with its tags is in flight, check it, yield a `RunRequest`. A failing item is logged and the others still launch; the tick fails, naming the items, only when nothing launched.

**Evaluate.** `git_pull_request_evaluate_sensor` loops over enabled projects (`?enabled=true`), their active project resources and the `UNKNOWN` pull requests of each, and launches `evaluate_repository_pull_requests_job`. The job maps `evaluate_pull_request` over them, 3 at a time, with an op retry policy of 3 retries (5 s, exponential). Filters are query options on nexus-api; Dagster does not filter lists in Python. nexus-api owns the match rule; the parser trusts the trigger's `spec_files`: none or several gives `REJECTED`, one is read at the merge commit.

**The 409-as-skip rule.** A 409 means nexus-api already moved on ([0005](0005-state-transition-tables.md)), so Dagster logs it and goes on. This applies to: creating a task for a pull request that is no longer `UNKNOWN`, whose project resource is inactive, or whose project is disabled or revoked (`record_outcome`), which leaves the pull request `UNKNOWN` to be evaluated again once nexus-api accepts a task; a run-status sensor patching a task that is already final; the sync job patching a result that already moved. A 400 from the task route is logged (nexus-api recorded the rejection). Any other error raises.

**One interval.** Every sensor uses `fnDagster.sensors.minIntervalSeconds` (default 30; env `DAGSTER_SENSORS_MIN_INTERVAL_SECONDS`; the dev values use 5), read once in `dagster/app/config.py`. Related values under `fnDagster.sensors`: `retryIntervalSeconds` (60) and `deliveryMaxAttempts` (5).

**Sensors default to STOPPED.** `fnDagster.sensors.initialStatus` is `STOPPED` and applies to a sensor Dagster has not seen before. `fncli start-sensor --group all` starts them in the order in `dagster/fncli/cmds/sensor.py`. The order does not matter: a run-status sensor only sees events from when it starts, and the reconcile sensor sets a task whose event was missed to the status of its run. `stop-sensor` goes the other way round.

**Launcher and task status.** The launcher lists the `PENDING` tasks of enabled projects with one `GET /tasks?status=PENDING&project_enabled=true` (nexus-api filters, [0021](0021-nexus-api-owns-the-record-and-the-rules.md)) and calls `POST /projects/<pid>/tasks/<id>/launch` once for each ([0009](0009-task-pinned-to-its-configuration.md)), which returns the decision, `outcome` and `cause` ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)). The launcher holds no rule. On `fail` nexus-api has already moved the task to `FAILED` with the `state_cause` (cut at 1024 characters) and the launcher does nothing more; on `launch` the answer carries the task and its dataset, and the launcher builds the run request from it. nexus-api fails a task when, checked in this order: something the task uses is revoked or deleted (the cause starts "revoked: "), its pinned configuration changed, its dataset resource is not active, or the dataset's secret is disabled. This is the one other writer of the status besides the run-status sensors ([0003](0003-task-status-written-by-run-status-sensors.md)): no run will exist for these failures. A task that is no longer `PENDING` answers 409 and is skipped. Any other error (for example the launch call fails) leaves the task `PENDING`, is logged, and is retried on the next tick; its run key is unused because no run was created. The run key is `task/<id>/<attempt>`; a manual retry bumps the attempt. The run-status sensors and the reconcile sensor write `status` and `executor_run_id` (the Dagster run id, unique on `tasks`).

**Retries.** The keys, the retry interval and the delivery retry are in [0015](0015-run-keys-retries-and-results-pr-sync.md). Evaluate has the op retry policy above. Ingest has no op retry; the next sensor tick launches it again with a new slot.

## Consequences

- A failing repository, pull request or task costs one run or one log line, not the tick.
- Retrying is bounded by the retry interval and, for delivery, by attempts.
- Each tick costs nexus-api one task list for the launcher and one for the reconcile sensor, whatever the number of projects, one list per project for evaluate, and the ingest sensor calls the provider once per repository.
- A task's status mirrors its run, except for the launcher's rule failures.

## Alternatives considered

- **Ingest in the sensor tick:** one failing repository fails the whole tick and nothing shows in the run list.
- **A per-sensor interval:** one chart value is simpler.
- **Dagster filters lists itself:** filters are nexus-api query options.

## Where it lives

- `dagster/app/definitions/sensors/base.py`, `git/` (`pr_ingest.py`, `ingest_job.py`, `pr_evaluate.py`, `evaluate_job.py`, `pr_parser.py`), `task/` (`launcher.py`, `run_status.py`, `delivery.py`, `pull_request_sync.py`)
- `dagster/app/config.py`, `dagster/app/backend.py`; `dagster/fncli/cmds/sensor.py`
- Chart: `k8s/federated-node/values.yaml` (`fnDagster.sensors`), `templates/dagster-env-config.yaml`

## Open questions

- The ingest sensor still calls the provider in `ready()`, so it is not thin in fact.
- A delivery stays `FAILED` after `deliveryMaxAttempts` with no alert.
- Whether the run-status sensors are worth replacing with run-status hooks on the job itself.
- The Dagster service account's access to secrets is broader than the credentials it reads, and the code server is not restarted after a credential rotation.
