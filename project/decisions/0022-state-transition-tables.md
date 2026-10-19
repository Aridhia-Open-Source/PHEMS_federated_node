# 0022. State transition tables for triggers, tasks and results

- Status: Accepted (built). 2026-10-19.
- Extends [0017](0017-task-status-written-by-run-status-sensors.md) and [0008](0008-polymorphic-result-and-forward-only-state.md). The 409s are decision 12 and 13 of [0019](0019-global-resources-and-shared-pull-requests.md). Related: [0021](0021-pull-requests-stored-once-fan-out-and-cursors.md), [0023](0023-dagster-pipeline-ops-sensors-and-retries.md).

## Context

Triggers, tasks and delivery results each have a state that should only move one way. Two writers can race: a delivery retry recording `OPENED` after the sync sensor found `MERGED`, a run-status sensor reporting a late `RUNNING` for a task that already failed. If the API accepts any valid value, a late or mistaken write undoes a final state.

## Decision

The allowed moves are data, in tables next to the enums in `webserver/app/models`. Two helpers in `webserver/app/helpers/state_rules.py` check them. Writing the same value again is always allowed. Any other refused move raises `InvalidRequest` with status 409 (the request is valid but conflicts with the current state).

- `transition(moves, current, new)`: `new` must be in `moves[current]`.
- `forward_only(order, current, new)`: `new` must have a higher rank than `current`.

**Trigger** (`TRIGGER_MOVES` in `trigger_state.py`, checked by `Trigger.set_state`): `UNKNOWN` to `YIELDED` or `REJECTED`; `YIELDED` and `REJECTED` have no moves, so both are final. `state_cause` is required for `REJECTED` and refused otherwise. A task is created only from an `UNKNOWN` trigger of an active link; a `REJECTED` or `YIELDED` trigger gives 409.

**Task** (`TASK_MOVES` and `RETRYABLE` in `task_status.py`, used by `patch_task` and `retry_task` in `tasks_api.py`): forward only.
- `PENDING` may go to `QUEUED`, `RUNNING` or a finished status (the sensors can see a run start before it is queued); `QUEUED` to `RUNNING` or a finished status; `RUNNING` to a finished status.
- `SUCCESS`, `FAILED` and `CANCELED` have no moves.
- The only way out is `POST /projects/<pid>/tasks/<id>/retry`. It needs `FAILED` or `CANCELED` (`RETRYABLE`), sets `PENDING`, adds 1 to `attempt` and clears the run fields. A retry of any other status is a 400, not a 409: `retry_task` raises `InvalidRequest` without a status.

**Result step** (`RESULT_ORDER` in `pull_request_result_step.py`, checked by `PullRequestResult.set_step`, called from `PATCH /projects/<pid>/results/<id>`):
- `UNKNOWN` (0) < `PUSHED` (1) < `OPENED` (2) < `MERGED` = `CLOSED` = `REVOKED` = `STALE` (all 3).
- The last four are terminal and of equal rank, so none moves to another.
- `REVOKED` and `STALE` are normally set when `POST /projects/<pid>/results` creates the result (revoked link, changed task configuration). `POST` also moves an existing, non-final result to `REVOKED` when its link was revoked since. Nothing is delivered for either.

**Result state** (`result_state.py`: `IN_PROGRESS`, `DELIVERED`, `FAILED`) is a separate column from the step. It has no move table: `PATCH` accepts any valid value. A `FAILED` result whose step is not final, on an active link, is relaunched by the delivery retry sensor ([0023](0023-dagster-pipeline-ops-sensors-and-retries.md)).

**Dagster copies the enums, not the tables.** `dagster/app/models/` repeats the values (the step also has `from_git`). There is no copy of `TRIGGER_MOVES`, `TASK_MOVES` or `RESULT_ORDER` there: Dagster sends the move and the webserver decides.

## Consequences

- A final state cannot be undone by a late or wrong write, and the check is in one place per entity.
- A new status or step needs an entry in its table, or every move to it is refused. The Dagster enum is a separate manual step.
- 0017's "PATCH accepts any valid status" no longer holds; it is a 409 out of a final status.
- The run-status sensors and the delivery and sync jobs treat the 409 as "already moved on" and skip ([0023](0023-dagster-pipeline-ops-sensors-and-retries.md)).
- Retry is the only controlled reopening of a task. There is no stale-task retry: a `STALE` result stays final.

## Alternatives considered

- **Leave the order to the sensors:** the races between writers (0017) come back.
- **Database constraints or triggers:** they cannot express "from state X" without the old value, and would be a second place for the rule.
- **A state-machine library:** more machinery than three small tables.
- **400 for a refused move:** 409 was chosen because the input is valid but conflicts with the current state. The 400 on retry is a different case, a request that does not apply to the status.

## Where it lives

- `webserver/app/models/trigger_state.py`, `task_status.py`, `pull_request_result_step.py`, `result_state.py`
- `webserver/app/helpers/state_rules.py`
- `webserver/app/models/trigger.py`, `pull_request_result.py`; `webserver/app/tasks_api.py`, `results_api.py`, `project_trigger_repositories_api.py`
- `dagster/app/models/` (enum copies)

## Not built or open

- Result `state` has no move table (should `DELIVERED` be final?).
- The `ResultState` docstring in the webserver says `FAILED` is one "nothing retries"; the retry sensor does retry it unless the step is final or attempts run out. The docstring is out of date.
- `POST /projects/<pid>/tasks/<id>/cancel` raises not implemented.
- No test was found that compares the Dagster enums with the webserver's; a drift would only show at runtime.
