# 0017. Task status is written only by run-status sensors

- Status: Accepted

## Context

Several components could set a task's status (the launcher, the delivery job, the backend). Racing writers make a status untrustworthy.

## Decision

- `TaskStatus` is `PENDING`, `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELED`; Dagster's vocabulary is mapped into it (`STARTED` to `RUNNING`, `FAILURE` to `FAILED`) and never stored.
- The launcher (`task_launcher_sensor`) only yields a `RunRequest` per `PENDING` task of an enabled project; it patches nothing. The run key `task/<id>/<attempt>` de-duplicates the re-yield until the run exists.
- Five run-status sensors (queued, started, success, failure, canceled) on `k8s_pipes_job` patch the task with the mapped status and the run id; `started_at` at start, `completed_at` at a terminal status. They act only on runs tagged `trigger=task`.
- `deliver_results_job` runs are tagged `trigger=delivery` and `delivery_task_id`, never `task_id`, so a delivery run is never mistaken for a task run and delivery cannot change the task.
- Retry: `POST /tasks/<id>/retry` accepts only `FAILED` or `CANCELED`, sets `PENDING`, bumps `attempt` and clears run fields; the new attempt gets a new run key.

## Consequences

- A task's status is a mirror of its run; it cannot be wrong for another reason than a sensor not running.
- The status sensors must be running before the launcher.
- `PATCH /tasks/<id>` accepts any valid status, and `POST /tasks/<id>/cancel` is not implemented (`NotImplementedException`).

## Alternatives considered

- **Launcher marks the task QUEUED**: rejected, it races the run-status sensor.
- **Backend polls Dagster**: rejected, Dagster owns run state.
