# 0001. Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger

## Context

A task can be requested in two ways: a pull request merged in a watched repository, or a direct `POST /projects/<id>/tasks`. Both need a durable record of why the task exists and whether the request was acceptable. A merged pull request also has to be recorded before it is evaluated, because ingest (polling the git provider) and evaluation (reading and validating the spec) are separate steps.

## Decision

- `triggers` is a joined-table parent (`Trigger`, discriminator `type`) with two children sharing its id: `pull_request_triggers` (`PullRequestTrigger`, type `PR`) and `api_request_triggers` (`ApiRequestTrigger`, type `API`).
- The parent holds what every trigger has: `project_id`, `state` and `state_cause`. `state` is `UNKNOWN`, `YIELDED` or `REJECTED`. A check constraint requires `state_cause` exactly when the state is `REJECTED`; `Trigger.set_state` enforces the same in code. The allowed moves are in [0005](0005-state-transition-tables.md).
- A `PullRequestTrigger` is a project's evaluation of one stored pull request. It is created `UNKNOWN` by the fan-out of the ingest ([0011](0011-pull-requests-stored-once-fan-out-and-cursors.md)), only for a project resource that watches the pull request. The evaluate job then either creates a task (the backend marks the trigger `YIELDED` in the same transaction) or records `REJECTED` with the cause (no spec file, several, or an invalid spec). A pull request that is not for a project gets no trigger at all, so there is no ignored state.
- An `ApiRequestTrigger` is validated inside `POST /projects/<id>/tasks`: it is recorded first, then `REJECTED` with the cause when invalid, else `YIELDED` together with its task.
- One task per trigger: `tasks.trigger_id` is `UNIQUE`. The task-creating endpoint for a pull request trigger is idempotent and returns the existing task.
- A trigger is never changed by the runs it leads to. Run progress lives on the task.

## Consequences

- Rejected pull requests stay visible with a reason, and are not re-evaluated.
- `Task` is independent of how it was requested; it points at `triggers` only.
- A new trigger kind is a new child table, with no change to the task side.
- Delivery of results needs the task's trigger to be a pull request ([0013](0013-results-delivered-as-branch-and-pull-request.md)).
