# 0026. State transition tables for triggers, tasks and results

- Status: Accepted (built)
- Split out of [0019](0019-global-resources-and-shared-pull-requests.md). Extends [0017](0017-task-status-written-by-run-status-sensors.md) (who writes task status), which said `PATCH` accepts any valid status; that is no longer true. Related: [0023](0023-pull-requests-stored-once-fan-out-and-cursors.md), 0025 (switching off and revoking), 0027 (Dagster pipeline).

## Context

Triggers, tasks and delivery results each have a state or status that should only move one way. The rules lived in prose, in the docs diagrams and, for the result step, in a docstring. The webserver accepted any valid value, so a late write (a delivery retry recording `OPENED` after the sync sensor found `MERGED`) or a mistaken `PATCH` could undo a final state.

## Decision

The allowed moves are data, in tables next to the enums in `webserver/app/models`, and two helpers in `webserver/app/helpers/state_rules.py` check them. Setting the same value again is always allowed. Any other refused move raises `InvalidRequest` with 409.

- `transition(moves, current, new)`: `new` must be in `moves[current]`.
- `forward_only(order, current, new)`: `new` must have a higher rank than `current`.

**Trigger** (`trigger_state.py: TRIGGER_MOVES`, used by `Trigger.set_state` in `models/trigger.py`):
- `UNKNOWN` to `YIELDED` or `REJECTED`; `YIELDED` and `REJECTED` have no moves, both final.
- `state_cause` is required for `REJECTED` and refused otherwise (`set_state`, plus check constraint `ck_triggers_state_cause_for_rejected` in the baseline).
- Only an `UNKNOWN` trigger of an active link can get a task (`post_task`, see 0023).

**Task** (`task_status.py: TASK_MOVES`, `RETRYABLE`, used in `tasks_api.py: patch_task` and `retry_task`):
- Statuses: `PENDING`, `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELED`.
- Forward only. `PENDING` may go to any later status (the sensors can see a run start before it is queued); `QUEUED` to `RUNNING` or a finished status; `RUNNING` to a finished status.
- `SUCCESS`, `FAILED` and `CANCELED` have no moves. The only way out is `POST /projects/<pid>/tasks/<id>/retry`, which needs `FAILED` or `CANCELED` (`RETRYABLE`), sets `PENDING`, adds 1 to `attempt` and clears run fields. A retry of any other status is a 400, not a 409.

**Result step** (`pull_request_result_step.py: RESULT_ORDER`, used by `PullRequestResult.set_step`, called from `results_api.py` on `PATCH`):
- `UNKNOWN` (0) < `PUSHED` (1) < `OPENED` (2) < `MERGED`, `CLOSED`, `REVOKED`, `STALE` (all 3).
- The last four are terminal siblings: equal rank, so none moves to another.
- `REVOKED` and `STALE` are created directly by `POST /projects/<pid>/results` (revoked link, changed configuration); nothing is delivered for them.

**Result state** (`result_state.py`): `IN_PROGRESS`, `DELIVERED`, `FAILED`, a separate column from the step. It has no move table: `PATCH` accepts any valid value. A `FAILED` result with a non-final step is retried by `results_delivery_retry_sensor` once its link is active.

**Dagster mirrors the enums, not the tables.** `dagster/app/models/trigger_state.py`, `task_status.py`, `pull_request_result_step.py` and `result_state.py` repeat the values (the step also has `from_git`). There is no copy of `TRIGGER_MOVES`, `TASK_MOVES` or `RESULT_ORDER` in `dagster/`. Dagster sends the move and the webserver decides.

## Consequences

- A final state cannot be undone by a late or wrong write; the check is in one place per entity.
- A new status or step needs a row in the table, or every move to it is refused. Adding a value to the Dagster enum is a separate manual step.
- 0017's consequence "`PATCH /tasks/<id>` accepts any valid status" no longer holds. Whether the run-status sensors handle a 409 on an already finished task was not checked.
- Retry is the only controlled reopening; there is no stale-task retry.

## Alternatives considered

- **Leave the order to the sensors.** Races between writers (see 0017) come back.
- **Database check constraints or triggers.** Cannot express "from state X" without the old value, and would be a second place for the rule.
- **A state-machine library.** More machinery than three small dicts.
- **One shared 400 for refused moves.** 409 was chosen because the request is valid but conflicts with the current state.

## Where it lives

- Tables and helpers: PR #555 (branch `split/01-schema`).
- Enforcement in the API: PR #556 (branch `split/02-webserver`).
- `webserver/app/models/trigger_state.py`, `task_status.py`, `pull_request_result_step.py`, `result_state.py`
- `webserver/app/helpers/state_rules.py`
- `webserver/app/models/trigger.py`, `pull_request_result.py`; `webserver/app/tasks_api.py`, `results_api.py`, `project_trigger_repositories_api.py`
- `dagster/app/models/` (enum copies)

## Not built or open

- `docs/architecture/entities.md` is stale on these tables: the task diagram says "the backend does not enforce the order"; the result diagram says a refused move is a 400 (the code gives 409), omits `STALE`, and does not show the separate `state`.
- The `ResultState` docstring in the webserver says `FAILED` is "nothing retries it"; the Dagster copy and the retry sensor say it is retried unless the step is final. Not reconciled.
- Result `state` has no move table (open: should `DELIVERED` be final?).
- `POST /tasks/<id>/cancel` is still not implemented (0017).
- The tables are not cross-checked against the Dagster enums by a test; a drift would only show at runtime.
