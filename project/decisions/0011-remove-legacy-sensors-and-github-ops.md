# 0011. Remove the legacy GitHub/Gitea sensors and the GitHub transfer/comment ops

- Status: Accepted (chart leftovers are a follow-up)

## Context

Before the trigger/task model, each provider had its own sensors that evaluated pull requests inside the tick, launched runs straight from them, and wrote a status on the pull request; on success a GitHub path launched a transfer job and commented on the trigger PR. The model change ([0001](0001-polymorphic-triggers.md)) removed the pull request status they wrote.

## Decision

Remove the legacy provider-specific sensors in the same change as the model, and replace them with provider-neutral ones: ingest, evaluate, launcher, run-status, delivery, sync ([0005](0005-git-api-protocol-and-factory.md), [0017](0017-task-status-written-by-run-status-sensors.md)). Remove `github_transfer_job`, the PR-comment job and ops, and the client methods only they used. Results go through `deliver_results_job` ([0007](0007-results-delivered-as-branch-and-pull-request.md)).

## Consequences

- Commenting the outcome on the trigger PR (a `REJECTED` cause, a results link) is not implemented.
- Leftovers not yet cleaned: `GH_RESULTS_DIR`, `GH_DELIVERY_REPO`, `github-token` secret requirement in the chart, and `SensorConfig`/`GithubConfig` env classes.

## Alternatives considered

- **Keep legacy sensors alongside**: rejected, they wrote fields that no longer exist and launched untracked runs.
- **Port the comment op to the new model**: deferred.
