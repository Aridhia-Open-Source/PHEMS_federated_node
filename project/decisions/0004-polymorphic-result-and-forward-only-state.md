# 0004. Polymorphic Result, PullRequestResult, a forward-only step and a separate state

## Context

Delivery of a task's results has a lifecycle (pushed, opened, merged or closed) and can fail part way. The fact "how far did it get" must not be lost when it fails, and two actors write it (the delivery job and the sync sensor).

## Decision

- `results` is a joined-table parent (`Result`, discriminator `type`) with `pull_request_results` (`PullRequestResult`, type `PR`) as the only child. The parent holds `task_id`, `results_repository_id`, `attempts` and `error`; there is one row per `(task, results_repository_id)`. `results_repository_id` points at the project's results link ([0006](0006-global-resources-and-project-links.md)); the API shows the global repository's id.
- `PullRequestResult.step` is the furthest step reached: `UNKNOWN`, `PUSHED`, `OPENED`, `MERGED`, `CLOSED`, `REVOKED`, `STALE`. It only moves forward ([0005](0005-state-transition-tables.md)). `REVOKED` (something the task uses is revoked or deleted) and `STALE` (the task's configuration changed, [0009](0009-task-pinned-to-its-configuration.md)) are final: nothing is delivered. Other columns fill in as the steps are reached: `branch`/`commit_sha` (pushed), `number`/`url` (opened), `merged_at`/`merge_commit_sha` (merged).
- `PullRequestResult.state` is a separate column: `IN_PROGRESS`, `DELIVERED`, `FAILED`. A failure sets `state` to `FAILED`, records `error` and bumps `attempts`, and leaves `step` where it was, so the step always says how far delivery got.
- **Mirror naming.** The trigger side is `Trigger` / `PullRequestTrigger` / `ApiRequestTrigger` ([0001](0001-polymorphic-triggers.md)), the result side is `Result` / `PullRequestResult`. A `PullRequestTrigger` is the merged pull request the node watches; a `PullRequestResult` is the pull request it opens.
- **The delivery vocabulary stays on the child**, unlike the trigger where `state` is on the parent. A trigger's verdict is the same for every kind. A result's lifecycle belongs to its delivery mechanism (`MERGED` means nothing for another kind of delivery), so each child owns its step and state sets.
- The task's own status and the delivery are independent: a task is `SUCCESS` whether or not its results were delivered ([0003](0003-task-status-written-by-run-status-sensors.md)).
- Exposed at `/projects/<id>/results`: `GET` with filters (repeated `?step=` and `?state=`, `?active_link=true`), `POST` (idempotent per task and repository), `PATCH`. A result whose task is in another project is a 404.

## Consequences

- One column answers "where is this delivery", another "is it healthy".
- Adding another delivery kind is a new child table with its own step and state sets.
- A result with no results link cannot exist (`RESTRICT`).
- A `CLOSED` result is terminal: a pull request reopened on the provider is not followed, and one deleted on the provider stays at its last step.

## Alternatives considered

- **Separate status and merge status:** two columns that can contradict.
- **Delivery failure as a step:** it would lose how far delivery got.
- **Vocabulary on the `Result` parent:** see above.

## Open questions

- Whether `DELIVERED` should be final for the state column.
