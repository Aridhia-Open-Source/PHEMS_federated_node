# 0008. Polymorphic Result, PullRequestResult and one forward-only state

- Status: Accepted

## Context

Delivery of a task's results has a lifecycle (pushed, opened, merged or closed). The first model had a result status plus a separate merge status, which could disagree.

## Decision

- `results` is a joined-table parent (`Result`, discriminator `type`) with `pull_request_results` (`PullRequestResult`, type `PR`) as the only child today. The parent holds `task_id`, `results_repository_id`, `attempts`, `error`; one row per `(task, results_repository)`.
- `PullRequestResult.state` is one column: `UNKNOWN`, `PUSHED`, `OPENED`, `MERGED`, `CLOSED`. It records the furthest step reached. Other columns fill in stages: `branch`/`commit_sha` (pushed), `number`/`url` (opened), `merged_at`/`merge_commit_sha` (merged).
- A failure does not change `state`: it sets `error` and bumps `attempts`, so state always says how far delivery got.
- **Mirror naming**: the trigger side is `Trigger` / `PullRequestTrigger` / `ApiRequestTrigger`, the result side is `Result` / `PullRequestResult`. A `PullRequestTrigger` is the merged pull request we watch; a `PullRequestResult` is the pull request we open.
- **`state` stays on the child**, unlike the trigger where `state` is on the parent. A trigger's verdict is the same for every kind. A result's lifecycle belongs to its delivery mechanism (MERGED means nothing for a different kind of delivery), so each child owns its state vocabulary.
- The task's own status and the delivery are independent: a task is `SUCCESS` whether or not its results were delivered.

## Consequences

- One column answers "where is this delivery". Exposed at `/results` (`GET` with repeated `?state=`, `POST` idempotent per task and repository, `PATCH`).
- Adding another delivery kind is a new child table with its own state set.
- A result with no results repository cannot exist (`RESTRICT`).

## Alternatives considered

- **Separate status and merge_status**: rejected, two columns that can contradict.
- **State on the `Result` parent**: rejected, see above.
- **Mark delivery failure as a state**: rejected, it would lose how far it got.
