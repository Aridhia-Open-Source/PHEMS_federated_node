# Contents guide for reviewing the decisions and docs

Start here. It lists every decision record (ADR) with what to check, the other docs by topic, and a reading order. Terms: a **GlobalResource** is a `Dataset`, `TriggerRepository`, `ResultsRepository` or `GitProvider` (a `Secret` is only used by GlobalResources). A **ProjectResource** is a project's link to one: `ProjectDataset`, `ProjectTriggerRepository`, `ProjectResultsRepository`.

## Decision records

Each is in [project/decisions](../project/decisions/README.md). Add a row here when a record is added.

| No. | Title | Status | Check |
|---|---|---|---|
| [0001](../project/decisions/0001-polymorphic-triggers.md) | Polymorphic Trigger (pull request or API request) | Accepted | `state` sits on the parent; one task per trigger. |
| [0002](../project/decisions/0002-task-spec-and-derivation.md) | TaskSpec, and a Task derived from spec and trigger | Accepted | Bad specs are a 400 or a kept REJECTED trigger, never a 500. |
| [0003](../project/decisions/0003-project-scoped-git-repositories.md) | Project-scoped trigger and results repositories | Superseded by 0019 | Skip; read 0019. |
| [0004](../project/decisions/0004-secrets-and-secret-providers.md) | Generic Secret model and SecretProvider | Superseded by 0019 | Skip; the Secret rules are in [revoke-and-enabled.md](architecture/revoke-and-enabled.md#secrets). |
| [0005](../project/decisions/0005-git-api-protocol-and-factory.md) | GitAPI protocol and factory over Gitea and GitHub | Accepted | Both providers give the same results and map errors the same way. |
| [0006](../project/decisions/0006-github-ingest-pulls-endpoint.md) | Ingest merged pull requests through the pulls endpoint | Accepted | Cursor handling, paging, truncated file lists. |
| [0007](../project/decisions/0007-results-delivered-as-branch-and-pull-request.md) | Results delivered as a pushed branch plus a pull request | Accepted | Layout under `target_dir`, size cap, resume after a partial push. |
| [0008](../project/decisions/0008-polymorphic-result-and-forward-only-state.md) | Polymorphic Result, forward-only step | Accepted | A step only moves forward; MERGED, CLOSED, REVOKED and STALE are final. |
| [0009](../project/decisions/0009-sync-reconciler-and-operational-rules.md) | Monotonic PATCH, sync reconciler, run keys, known limits | Accepted (limits open) | Run keys and retries; launcher rules; the known limits are acknowledged. |
| [0010](../project/decisions/0010-gitea-port-4000-and-localhost-forward.md) | Gitea on port 4000, localhost forward | Accepted | In-cluster versus host URL translation. |
| [0011](../project/decisions/0011-remove-legacy-sensors-and-github-ops.md) | Remove the legacy sensors and GitHub ops | Accepted | No leftover chart values or env settings. |
| [0012](../project/decisions/0012-pydantic-dto-layer.md) | Pydantic DTO layer for API responses | Accepted | Responses go through DTOs; validation gives a 400. |
| [0013](../project/decisions/0013-baseline-migration-edited-in-place.md) | Baseline migration edited in place | Provisional | Only fine while no deployment holds data worth keeping. |
| [0014](../project/decisions/0014-dar-rename-and-detached-auth.md) | DAR rename; Keycloak and whitelisted images detached | Provisional | What is disconnected is listed and nothing else calls it. |
| [0015](../project/decisions/0015-fncli-dev-ops-tool.md) | fncli as a dev and ops tool | Accepted | Scope stays small; copied Dagster client code is on purpose. |
| [0016](../project/decisions/0016-tilt-dev-loop.md) | Tilt dev loop | Accepted | Dev only; the chart does not depend on it. |
| [0017](../project/decisions/0017-task-status-written-by-run-status-sensors.md) | Task status written only by run-status sensors | Accepted | Delivery never writes the status; an illegal move is a 409. |
| [0018](../project/decisions/0018-global-resources-and-gitea-mirror.md) | GlobalResources and a Gitea mirror (design note) | Proposed | History only; superseded by 0019 and 0020. |
| [0019](../project/decisions/0019-global-resources-and-shared-pull-requests.md) | GlobalResources assigned to projects, pull requests stored once | Accepted (built) | The model, fan-out and cursor rules, revoke versus enabled, soft delete, task configuration pinning, the listed gaps. |
| [0020](../project/decisions/0020-gitea-mirror-service.md) | Gitea mirror service | Proposed | A separate service, outbound only; not built. |

## Other docs by topic

Architecture ([docs/architecture](architecture/)):

- [entities.md](architecture/entities.md): schema (ER), the two inheritance trees, trigger state, task status, result step.
- [flows.md](architecture/flows.md): end to end flow, ingest and fan-out, component and network view, sensor and job inventory.
- [revoke-and-enabled.md](architecture/revoke-and-enabled.md): the two flags, what each state does, soft delete, Secrets, known limits.

Requirements and as-built ([project](../project/)):

- [moonshot-requirements.md](../project/moonshot-requirements.md): the requirements; its status block at the top says what has changed since.
- [moonshot-requirements-diff.md](../project/moonshot-requirements-diff.md): where the code differs from the requirements.
- [moonshot-as-built.md](../project/moonshot-as-built.md): what was built; read the status block first.
- [auth-mvp-plan.md](../project/auth-mvp-plan.md): research on user, admin and system tiers; not built.

Flows and testing ([project/handover](../project/handover/README.md)):

- [review-guide-shared-resources.md](../project/handover/review-guide-shared-resources.md): a code reading order for the `shared-resources` diff.
- [e2e-qa-plan.md](../project/handover/e2e-qa-plan.md), [e2e-results-2026-10-18.md](../project/handover/e2e-results-2026-10-18.md), [e2e-run1-fixes.md](../project/handover/e2e-run1-fixes.md): the live-cluster scenarios, the first run and its fixes.
- [laptop-handover-2026-10-18.md](../project/handover/laptop-handover-2026-10-18.md): the review stack, open decisions and what is stale.
- [gitea-mirror-plan.md](../project/handover/gitea-mirror-plan.md), [dagster-sensors-plan.md](../project/handover/dagster-sensors-plan.md), [split-plan.md](../project/handover/split-plan.md): plans for work not done yet.

Operations:

- [DEPLOYMENT.md](../DEPLOYMENT.md), [k8s/federated-node/README.md](../k8s/federated-node/README.md): install and chart values.
- [dagster/README.md](../dagster/README.md), [dagster/fncli/README.md](../dagster/fncli/README.md): the Dagster code location and the fncli tool.

Historical, not a design source: the other files in [project/handover](../project/handover/) (earlier session notes, the moonshot build plan and review). The decision records win where they differ.

## Suggested reading order

1. This guide and [entities.md](architecture/entities.md): the schema and the three state machines.
2. ADR [0019](../project/decisions/0019-global-resources-and-shared-pull-requests.md): the intent.
3. [revoke-and-enabled.md](architecture/revoke-and-enabled.md): what each flag does to each GlobalResource and ProjectResource.
4. ADRs [0001](../project/decisions/0001-polymorphic-triggers.md), [0002](../project/decisions/0002-task-spec-and-derivation.md), [0008](../project/decisions/0008-polymorphic-result-and-forward-only-state.md), [0017](../project/decisions/0017-task-status-written-by-run-status-sensors.md): triggers, tasks, results and who writes which state.
5. ADRs [0005](../project/decisions/0005-git-api-protocol-and-factory.md) to [0007](../project/decisions/0007-results-delivered-as-branch-and-pull-request.md): the git side and delivery.
6. [flows.md](architecture/flows.md): the whole path from a merged pull request to a results pull request.
7. ADR [0009](../project/decisions/0009-sync-reconciler-and-operational-rules.md) and the sensor and job inventory in [flows.md](architecture/flows.md#sensor-and-job-inventory): run keys, retries, the launcher rules. This is the sensors part and comes last.
8. The remaining ADRs (0010 to 0016) as needed; skip 0003, 0004 and 0018.
