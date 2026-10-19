# 0023. The Dagster pipeline: ingest as an op, eleven sensors, one interval, retries

- Status: Accepted (built). 2026-10-19.
- Replaces section 4 of [0019](0019-global-resources-and-shared-pull-requests.md) (Dagster side). Run keys and the sync reconciler stay in [0009](0009-sync-reconciler-and-operational-rules.md); who writes the task status stays in [0017](0017-task-status-written-by-run-status-sensors.md), amended below. Related: [0021](0021-pull-requests-stored-once-fan-out-and-cursors.md), [0022](0022-state-transition-tables.md).

## Context

Pull requests are stored once per global repository ([0021](0021-pull-requests-stored-once-fan-out-and-cursors.md)), so the pipeline has to poll once per repository and keep one failing repository, pull request or task from stalling the rest. Slow work should run as a visible Dagster run, and the sensors should mostly decide what to launch.

## Decision

**Eleven sensors** (`dagster/app/definitions/sensors/`), 2 in `git/` and 9 in `task/`:
- `git_pull_request_ingest_sensor`, `git_pull_request_evaluate_sensor`
- `task_launcher_sensor`
- five run-status sensors on `k8s_pipes_job`: `task_queued_sensor`, `task_started_sensor`, `task_success_sensor`, `task_failure_sensor`, `task_canceled_sensor`
- `task_results_delivery_sensor` (a run-status sensor too: on a task run's `SUCCESS` it requests `deliver_results_job`)
- `results_delivery_retry_sensor`, `results_pull_request_sync_sensor`

**Ingest is an op.** The ingest sensor launches one `ingest_pull_requests_job` run per pollable repository (`GET /global/repositories/triggers?pollable=true`: repository, provider and secret enabled, project links ignored). Its `ready()` still asks the provider whether anything merged since the cursor. The op `ingest_pull_requests` re-reads the repository for its current cursor, fetches the merged pull requests and their files, sorts them by `(merged_at, number)` and posts them in batches of at most 100 (`MAX_BATCH_SIZE`; `BackendAPI.create_pull_requests_batch` refuses more). The cursor only moves when a batch is stored, so a failed batch never leaves an older pull request unposted behind a newer one. Duplicate file paths are dropped before the post.

**Per-repository isolation.** The ingest, evaluate and delivery-retry sensors share `LaunchingSensor` (`sensors/base.py`): per item, skip it if a run with its tags is in flight, check it, yield a `RunRequest`. A failing item is logged and the others still launch; the tick fails, naming the items, only when nothing launched.

**Evaluate.** `git_pull_request_evaluate_sensor` loops over enabled projects (`?enabled=true`), their active links and the `UNKNOWN` pull requests of each, and launches `evaluate_repository_pull_requests_job`. The job maps `evaluate_pull_request` over them, 3 at a time, with an op retry policy of 3 retries (5 s, exponential). Filters are query options on the webserver; Dagster does not filter lists in Python. The webserver owns the match rule; the parser trusts the trigger's `spec_files`: none or several gives `REJECTED`, one is read at the merge commit.

**The 409-as-skip rule.** A 409 means the webserver already moved on, so Dagster logs it and goes on. This applies to: creating a task for a pull request that is no longer `UNKNOWN` or whose link is inactive (`record_outcome`); a run-status sensor patching a task that is already final; the sync job patching a result that already moved. A 400 from the task route is logged (the backend recorded the rejection). Any other error raises.

**One interval.** Every sensor uses `fnDagster.sensors.minIntervalSeconds` (default 30; env `DAGSTER_SENSORS_MIN_INTERVAL_SECONDS`; the dev values use 5), read once in `dagster/app/config.py`. Related values under `fnDagster.sensors`: `retryIntervalSeconds` (60) and `deliveryMaxAttempts` (5).

**Sensors default to STOPPED.** `fnDagster.sensors.initialStatus` is `STOPPED` and applies to a sensor Dagster has not seen before. `fncli start-sensor --sensor all` starts them in the order in `dagster/fncli/cmds/sensor.py`: the five run-status sensors, the delivery sensor, the results sync and delivery retry sensors, then ingest, evaluate and the launcher last. Run-status sensors only see events from when they start, so a run that finishes first would leave its task `PENDING`. `stop-sensor` goes the other way round.

**Launcher and task status.** The launcher lists `PENDING` tasks of enabled projects and calls `GET /projects/<pid>/tasks/<id>/config`. It patches the task `FAILED` with a `state_cause` (cut at 1024 characters) when: something the task uses is revoked or deleted, its pinned configuration changed, its dataset link is not active, or the dataset's secret is disabled. This amends 0017, which said the launcher patches nothing: it is the one other writer of the status, for failures where no run will exist. Any other error leaves the task `PENDING`, is logged, and is retried on the next tick. The run key is `task/<id>/<attempt>`. A manual retry ([0022](0022-state-transition-tables.md)) bumps the attempt. The run-status sensors write `status` and `executor_run_id` (the Dagster run id, unique on `tasks`).

**Retries** (details of keys in [0009](0009-sync-reconciler-and-operational-rules.md)):
- Sensor runs with an unchanged input are relaunched once per `retryIntervalSeconds`, because `run_key` ends in a time slot.
- Delivery: `results_delivery_retry_sensor` relaunches `FAILED` results on an active link whose step is not final, until `deliveryMaxAttempts` failed attempts. After that the result stays `FAILED` until relaunched by hand.
- Evaluate: the op retry policy above.
- Ingest: no op retry; the next sensor tick launches it again with a new slot.

## Consequences

- A failing repository, pull request or task costs one run or one log line, not the tick.
- Retrying is bounded by the retry interval and, for delivery, by attempts.
- Each tick costs the webserver one list per project (evaluate), and the ingest sensor calls the provider once per repository.
- A task's status mirrors its run, except for the launcher's rule failures.

## Alternatives considered

- **Ingest in the sensor tick** (the old way): one repository fails the whole tick and nothing shows in the run list.
- **A per-sensor interval:** one chart value is simpler.
- **Launcher marks the task `QUEUED`:** rejected in 0017, it races the run-status sensor.
- **Dagster filters lists itself:** filters are webserver query options.

## Where it lives

- `dagster/app/definitions/sensors/base.py`, `git/` (`pr_ingest.py`, `ingest_job.py`, `pr_evaluate.py`, `evaluate_job.py`, `pr_parser.py`), `task/` (`launcher.py`, `run_status.py`, `delivery.py`, `pull_request_sync.py`)
- `dagster/app/config.py`, `dagster/app/backend.py`; `dagster/fncli/cmds/sensor.py`
- Chart: `k8s/federated-node/values.yaml` (`fnDagster.sensors`), `templates/dagster-env-config.yaml`

## Not built or open

- The ingest sensor still calls the provider in `ready()`, so it is not thin in fact.
- A delivery stays `FAILED` after `deliveryMaxAttempts` with no alert.
- The exit code is not recorded: nothing sets `exit_code` from a run.
- `POST /projects/<pid>/tasks/<id>/cancel` is not implemented.
