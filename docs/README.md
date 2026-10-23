# Contents guide for reviewing the decisions and docs

Start here. It lists every decision record (ADR) with what to check, the other docs by topic, and a reading order. Terms: a **GlobalResource** is a `Dataset`, `TriggerRepository`, `ResultsRepository` or `GitProvider` (a `Secret` is only used by GlobalResources). A **ProjectResource** is a project's link to one: `ProjectDataset`, `ProjectTriggerRepository`, `ProjectResultsRepository`.

## Decision records

Each is in [project/decisions](../project/decisions/README.md). Add a row here when a record is added.

| No. | Title | Check |
|---|---|---|
| [0001](../project/decisions/0001-polymorphic-triggers.md) | Polymorphic Trigger (pull request or API request) | `state` sits on the parent; one task per trigger. |
| [0002](../project/decisions/0002-task-spec-and-derivation.md) | TaskSpec, and a Task derived from spec and trigger | Bad specs are a 400 or a kept REJECTED trigger, never a 500. |
| [0003](../project/decisions/0003-task-status-written-by-run-status-sensors.md) | Task status written by the run-status and reconcile sensors | Delivery never writes the status; the launcher writes FAILED only for a rule. |
| [0004](../project/decisions/0004-polymorphic-result-and-forward-only-state.md) | Polymorphic Result, forward-only step, separate state | A step only moves forward; MERGED, CLOSED, REVOKED and STALE are final. |
| [0005](../project/decisions/0005-state-transition-tables.md) | State transition tables | `TRIGGER_MOVES`, `TASK_MOVES`, `RETRYABLE`, `RESULT_ORDER`; 409 on a refused move, 400 on a bad retry. |
| [0006](../project/decisions/0006-global-resources-and-project-links.md) | Global resources linked to projects | The tables and links, the URL layout, datasets and the default dataset, cross-project loops. |
| [0007](../project/decisions/0007-secrets-and-secret-providers.md) | Generic Secret model and SecretProvider | A secret is a reference; the Secret rules are in [revoke-and-enabled.md](architecture/revoke-and-enabled.md#secrets). |
| [0008](../project/decisions/0008-enabled-revoked-and-soft-delete.md) | Enabled, revoked and soft delete | The two flags, what each state does, soft delete, the listed gaps. |
| [0009](../project/decisions/0009-task-pinned-to-its-configuration.md) | A task is pinned to its configuration | What the snapshot holds, the checks before launch and publish. |
| [0010](../project/decisions/0010-git-api-protocol-and-factory.md) | GitAPI protocol and factory over Gitea and GitHub | Both providers give the same results and map errors the same way. |
| [0011](../project/decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md) | Pull requests stored once, fan-out, cursors | Match rule, the two cursors, `skip_gap`, backfill only at project enable. |
| [0012](../project/decisions/0012-github-ingest-pulls-endpoint.md) | Ingest merged pull requests through the pulls endpoint | Cursor handling, paging, truncated file lists. |
| [0013](../project/decisions/0013-results-delivered-as-branch-and-pull-request.md) | Results delivered as a pushed branch plus a pull request | Layout under `target_dir`, size cap, resume after a partial push. |
| [0014](../project/decisions/0014-dagster-pipeline-ops-sensors-and-retries.md) | Dagster pipeline: ingest op, twelve sensors | Batches of 100, one interval, STOPPED by default, any start order, 409 as skip. |
| [0015](../project/decisions/0015-run-keys-retries-and-results-pr-sync.md) | Run keys, retries and the results pull request sync | Run keys and retries; delivery retry; the sync reconciler's limits. |
| [0016](../project/decisions/0016-pydantic-dto-layer.md) | Pydantic DTO layer for API responses | Responses go through DTOs; validation gives a 400. |
| [0017](../project/decisions/0017-authorization-detached-from-dar-and-keycloak.md) | Authorization detached from DAR, Keycloak and whitelisted images | What is disconnected is listed and nothing else calls it. |
| [0018](../project/decisions/0018-fncli-dev-ops-tool.md) | fncli as a dev and ops tool | Scope stays small; models are imported, not copied. |
| [0019](../project/decisions/0019-gitea-port-4000-and-localhost-forward.md) | Gitea on port 4000, localhost forward | In-cluster versus host URL translation. |
| [0020](../project/decisions/0020-tilt-dev-loop.md) | Tilt dev loop | Dev only; the chart does not depend on it. |
| [0021](../project/decisions/0021-webserver-owns-the-record-and-the-rules.md) | Webserver owns the record and the rules | Dagster asks and acts; the launcher fails or launches as the config answer says. |
| [0022](../project/decisions/0022-task-isolation.md) | Task isolation: storage, secrets, namespace and network | Each part separates what is built from what is decided and not built (#536); NetworkPolicy is not built. |

## Other docs by topic

Architecture ([docs/architecture](architecture/)):

- [entities.md](architecture/entities.md): schema (ER), the two inheritance trees, trigger state, task status, result step.
- [flows.md](architecture/flows.md): end to end flow, ingest and fan-out, component and network view, sensor and job inventory.
- [revoke-and-enabled.md](architecture/revoke-and-enabled.md): the two flags, what each state does, soft delete, Secrets, known limits.
- [sensors/README.md](architecture/sensors/README.md): one doc per Dagster sensor with a flow chart (the status mirrors are grouped), plus the shared sensor helpers.

Research ([project](../project/)):

- [auth-mvp-plan.md](../project/auth-mvp-plan.md): research on user, admin and system tiers; not built.

Testing and open items:

- [dagster/fncli/tests/e2e/README.md](../dagster/fncli/tests/e2e/README.md): how to run the live-cluster end-to-end suites.
- The mirror service is developed on branch `moonshot/gitea-mirror`.

Operations:

- [DEPLOYMENT.md](../DEPLOYMENT.md), [k8s/federated-node/README.md](../k8s/federated-node/README.md): install and chart values.
- [dagster/README.md](../dagster/README.md), [dagster/fncli/README.md](../dagster/fncli/README.md): the Dagster code location and the fncli tool.

## Suggested reading order

1. This guide and [entities.md](architecture/entities.md): the schema and the three state machines.
2. ADRs [0001](../project/decisions/0001-polymorphic-triggers.md), [0002](../project/decisions/0002-task-spec-and-derivation.md), [0003](../project/decisions/0003-task-status-written-by-run-status-sensors.md), [0004](../project/decisions/0004-polymorphic-result-and-forward-only-state.md) and [0005](../project/decisions/0005-state-transition-tables.md): triggers, tasks, results and who writes which state.
3. ADRs [0006](../project/decisions/0006-global-resources-and-project-links.md) to [0009](../project/decisions/0009-task-pinned-to-its-configuration.md): global resources and their links, secrets, the two flags and soft delete, and task pinning. [revoke-and-enabled.md](architecture/revoke-and-enabled.md) shows what each flag does to each resource.
4. ADRs [0010](../project/decisions/0010-git-api-protocol-and-factory.md) to [0013](../project/decisions/0013-results-delivered-as-branch-and-pull-request.md): the git side, pull requests and cursors, and delivery.
5. [flows.md](architecture/flows.md): the whole path from a merged pull request to a results pull request.
6. ADRs [0014](../project/decisions/0014-dagster-pipeline-ops-sensors-and-retries.md) and [0015](../project/decisions/0015-run-keys-retries-and-results-pr-sync.md) and the sensor and job inventory in [flows.md](architecture/flows.md#sensor-and-job-inventory): run keys, retries, the launcher rules. Then the [sensors docs](architecture/sensors/README.md), one per sensor.
7. ADRs [0016](../project/decisions/0016-pydantic-dto-layer.md) to [0020](../project/decisions/0020-tilt-dev-loop.md) as needed: DTOs, the detached authorization, and the tooling (fncli, Gitea, Tilt). [0021](../project/decisions/0021-webserver-owns-the-record-and-the-rules.md): who owns the rules. [0022](../project/decisions/0022-task-isolation.md): how a task is isolated, and what is still to build.
