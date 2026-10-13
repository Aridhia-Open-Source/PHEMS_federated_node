# 0001. Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger

- Status: Accepted

## Context

A task can be requested in two ways: a pull request merged in a watched repository, or a direct `POST /tasks`. Both need a durable record of why the task exists and whether the request was acceptable. A merged pull request also has to be recorded before it is evaluated, because ingest (polling the git provider) and evaluation (reading and validating the spec) are separate steps.

## Decision

- `triggers` is a joined-table parent (`Trigger`, discriminator `type`) with two children sharing its id: `pull_request_triggers` (`PullRequestTrigger`, type `PR`) and `api_request_triggers` (`ApiRequestTrigger`, type `API`).
- The parent holds what every trigger has: `project_id`, `state` and `state_cause`. `state` is `UNKNOWN`, `YIELDED`, `IGNORED` or `REJECTED`. A check constraint requires `state_cause` exactly when the state is `IGNORED` or `REJECTED`; `Trigger.set_state` enforces the same in code.
- A pull request trigger is recorded `UNKNOWN` by the ingest sensor. The evaluate job then either creates a task (the backend marks the trigger `YIELDED` in the same transaction), or records `IGNORED` (no new spec file under the watch dir) or `REJECTED` (several files, or an invalid spec) with the cause.
- One task per trigger: `tasks.trigger_id` is `UNIQUE`. The task-creating endpoint is idempotent and returns the existing task.
- A trigger is never changed by the runs it leads to. Run progress lives on the task.

## Consequences

- Rejected and ignored pull requests stay visible with a reason, and are not re-evaluated.
- `Task` is independent of how it was requested; it points at `triggers` only.
- A new trigger kind is a new child table, no change to the task side.
- `requested_by` is computed per child (`raised_by` or `user_id`).

## Alternatives considered

- **One wide table with nullable PR and API columns**: rejected, the columns of the two kinds do not overlap and constraints would be conditional.
- **Status on the pull request row driven by the run**: rejected, it mixed the verdict on the request with run progress (this is what the earlier PR status did).
- **Several tasks per trigger (retries as new tasks)**: rejected, a retry is the same task with the next `attempt` ([0009](0009-sync-reconciler-and-operational-rules.md)).
