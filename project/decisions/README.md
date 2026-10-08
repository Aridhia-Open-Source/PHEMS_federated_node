# Architecture decision records

Decisions behind the trigger, task and results pipeline of the Federated Node, written in MADR style (Status, Context, Decision, Consequences, Alternatives considered). Each was checked against the code at the tip of the delta split (`split/11-fncli-pipeline`). "Provisional" means decided for now but expected to change; open items are listed in the record itself.

New records are numbered in sequence as `NNNN-short-title.md` and added to the table.

## Diagrams

- [Entities and state machines](../../docs/architecture/entities.md): schema (ER), the two inheritance trees, trigger state, task status, results pull request state.
- [Flows and components](../../docs/architecture/flows.md): end-to-end flow, sequence across fncli, backend, Dagster and the git host, component and network view, sensor and job inventory.

## Index

| No. | Title | Status |
|---|---|---|
| [0001](0001-polymorphic-triggers.md) | Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger | Accepted |
| [0002](0002-task-spec-and-derivation.md) | TaskSpec, and a Task derived from spec and trigger | Accepted |
| [0003](0003-project-scoped-git-repositories.md) | Project-scoped trigger and results repositories | Accepted |
| [0004](0004-secrets-and-secret-providers.md) | Generic Secret model and SecretProvider; per-repository tokens | Accepted (the `GH_TOKEN` leftovers are a known follow-up) |
| [0005](0005-git-api-protocol-and-factory.md) | GitAPI protocol and GitAPIFactory over Gitea and GitHub | Accepted |
| [0006](0006-github-ingest-pulls-endpoint.md) | Ingest merged pull requests through the pulls endpoint, not search | Accepted |
| [0007](0007-results-delivered-as-branch-and-pull-request.md) | Results delivered as a pushed branch plus a results pull request | Accepted (size cap and layout are tuneable) |
| [0008](0008-polymorphic-result-and-forward-only-state.md) | Polymorphic Result, PullRequestResult and one forward-only state | Accepted |
| [0009](0009-sync-reconciler-and-operational-rules.md) | Monotonic PATCH rule, sync reconciler, STOPPED sensors, known limits | Accepted (the known limits are open) |
| [0010](0010-gitea-port-4000-and-localhost-forward.md) | Gitea on port 4000 in-cluster, localhost forward, fncli host translation | Accepted |
| [0011](0011-remove-legacy-sensors-and-github-ops.md) | Remove the legacy GitHub/Gitea sensors and the GitHub transfer/comment ops | Accepted (chart leftovers are a follow-up) |
| [0012](0012-pydantic-dto-layer.md) | Pydantic DTO layer for API responses | Accepted (applied to the models touched so far) |
| [0013](0013-baseline-migration-edited-in-place.md) | Baseline migration edited in place while the schema is not live | Provisional (until a deployment holds data worth keeping) |
| [0014](0014-dar-rename-and-detached-auth.md) | DAR rename; Keycloak and whitelisted images detached | Provisional (disconnected until the authorization rework) |
| [0015](0015-fncli-dev-ops-tool.md) | fncli as a dev/ops tool | Accepted (scope is deliberately small) |
| [0016](0016-tilt-dev-loop.md) | Tilt dev loop, with the tilt-run image for run pods | Accepted |
| [0017](0017-task-status-written-by-run-status-sensors.md) | Task status is written only by run-status sensors | Accepted |
