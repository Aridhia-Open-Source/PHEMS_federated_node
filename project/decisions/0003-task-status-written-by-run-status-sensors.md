# 0003. Task status is written by the run-status sensors and the reconcile sensor

## Context

Several components could set a task's status (the launcher, the delivery job, the backend). Racing writers make a status untrustworthy.

## Decision

- `TaskStatus` is `PENDING`, `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELED`. Dagster's vocabulary is mapped into it (`STARTED` to `RUNNING`, `FAILURE` to `FAILED`) and never stored.
- The launcher (`task_launcher_sensor`) yields a `RunRequest` per `PENDING` task of an enabled project and patches nothing when it launches. The one other write it makes is `FAILED`, with a `state_cause`, for a task whose launch a rule stops, since no run will exist for it ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)). The run key `task/<id>/<attempt>` de-duplicates the re-yield until the run exists.
- Five run-status sensors (queued, started, success, failure, canceled) on `k8s_pipes_job` patch the task with the mapped status and the run id (`executor_run_id`); `started_at` is set at start and `completed_at` at a terminal status. They act only on runs tagged `trigger=task`.
- `task_reconcile_sensor` repairs a missed event. Every tick it finds the run of each `PENDING`, `QUEUED` or `RUNNING` task of an enabled project by its tags (`trigger=task`, `task_id`, `attempt`), maps the run's current status to a task status with the same mapping and fields as the run-status sensors, and patches the task when the status differs. A `PENDING` task without a run is left to the launcher. It is level-triggered and its writes are idempotent, because the state tables refuse a repeat or a move back with a 409, which it skips.
- `deliver_results_job` runs are tagged `trigger=delivery` and `delivery_task_id`, never `task_id`, so a delivery run is never mistaken for a task run and delivery cannot change the task.
- The backend refuses a move that is not in `TASK_MOVES` with a 409 ([0005](0005-state-transition-tables.md)).
- Retry: `POST /projects/<id>/tasks/<id>/retry` accepts only `FAILED` or `CANCELED`, sets `PENDING`, bumps `attempt` and clears the run fields; the new attempt gets a new run key.

## Consequences

- A task's status mirrors its run, except for the launcher's rule failures.
- A run-status sensor that was stopped, restarted or missed an event leaves no task stale for more than a tick of the reconcile sensor, so the start order of the sensors does not matter ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)).
- `POST /projects/<id>/tasks/<id>/cancel` is not implemented (it raises `NotImplementedException`), so `CANCELED` only comes from a run canceled in Dagster.
- The exit code is not recorded: nothing sets `exit_code` from a run.

## Alternatives considered

- **Launcher marks the task QUEUED:** it races the run-status sensor.
- **Backend polls Dagster:** Dagster owns run state.

## Open questions

- Whether the task cancel route should stop the run in Dagster, and how the exit code is obtained from a run.
