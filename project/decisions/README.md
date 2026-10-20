# Architecture decision records

The architecture of the Federated Node's trigger, task and results pipeline, written in MADR style (Context, Decision, Consequences, Alternatives considered, Open questions). Together the records describe the system as it is; each is written in the present tense and open questions are listed at the end of the record they belong to.

New records are numbered in sequence as `NNNN-short-title.md` and added to the table below and to the one in [../../docs/README.md](../../docs/README.md), the reviewer's guide, which also says what to check in each record.

Open items and working notes: [../../HANDOVER.md](../../HANDOVER.md). The mirror service is developed on branch `moonshot/gitea-mirror`.

## Diagrams

- [Entities and state machines](../../docs/architecture/entities.md): schema (ER), the two inheritance trees, trigger state, task status, results pull request state.
- [Flows and components](../../docs/architecture/flows.md): end-to-end flow, sequence across fncli, backend, Dagster and the git host, component and network view, sensor and job inventory.

## Index

| No. | Title | Summary |
|---|---|---|
| [0001](0001-polymorphic-triggers.md) | Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger | A trigger records why a task exists; `state` sits on the parent; one task per trigger. |
| [0002](0002-task-spec-and-derivation.md) | TaskSpec, and a Task derived from spec and trigger | One normalised, validated spec from the two request shapes; the raw spec is kept on the trigger. |
| [0003](0003-task-status-written-by-run-status-sensors.md) | Task status is written by the run-status sensors and the reconcile sensor | The status mirrors the Dagster run, and the reconcile sensor repairs a missed event; the launcher only fails tasks a rule stops; delivery never writes it. |
| [0004](0004-polymorphic-result-and-forward-only-state.md) | Polymorphic Result, PullRequestResult, a forward-only step and a separate state | A delivery's step only moves forward; failure is a state, not a step. |
| [0005](0005-state-transition-tables.md) | State transition tables for triggers, tasks and result steps; 409 on a refused move | Allowed moves are data; a late or wrong write cannot undo a final state. |
| [0006](0006-global-resources-and-project-links.md) | Global resources, linked to projects | Secrets, git providers, repositories and datasets are global; a project reaches them through its own link; URL layout. |
| [0007](0007-secrets-and-secret-providers.md) | Generic Secret model and SecretProvider; per-repository tokens | A secret is a reference to a value in a store; each repository has its own token. |
| [0008](0008-enabled-revoked-and-soft-delete.md) | Enabled, revoked and soft delete | A person's switch and the controller's withdrawal are separate flags; deletes are soft. |
| [0009](0009-task-pinned-to-its-configuration.md) | A task is pinned to its configuration | A snapshot of results and dataset configuration fails or stales a task whose setup changed. |
| [0010](0010-git-api-protocol-and-factory.md) | GitAPI protocol and GitAPIFactory over Gitea and GitHub | Provider-neutral sensors and delivery over one protocol. |
| [0011](0011-pull-requests-stored-once-fan-out-and-cursors.md) | Pull requests stored once per repository, fanned out to project links, with cursors | One poll and one copy per repository; match rule, two cursors, `skip_gap` and backfill. |
| [0012](0012-github-ingest-pulls-endpoint.md) | Ingest merged pull requests through the pulls endpoint, not search | The list-pulls endpoint avoids the search rate limit and index lag. |
| [0013](0013-results-delivered-as-branch-and-pull-request.md) | Results delivered as a pushed branch plus a results pull request | Zip, spec and metadata pushed to a branch and opened as a reviewable pull request; resumable. |
| [0014](0014-dagster-pipeline-ops-sensors-and-retries.md) | The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries | Per-repository ingest runs, per-item isolation, 409 as skip, sensors stopped by default. |
| [0015](0015-run-keys-retries-and-results-pr-sync.md) | Run keys, retries and the results pull request sync | Run keys with a retry slot, delivery retry, and the sync reconciler. |
| [0016](0016-pydantic-dto-layer.md) | Pydantic DTO layer for API responses | Responses are built by DTOs; Dagster and fncli parse them into their own models. |
| [0017](0017-authorization-detached-from-dar-and-keycloak.md) | Authorization detached from DAR, Keycloak and whitelisted images | DAR and whitelisted images are disconnected until the authorization rework. |
| [0018](0018-fncli-dev-ops-tool.md) | fncli as a dev/ops tool | Idempotent step commands for setting up and exercising the Tilt cluster. |
| [0019](0019-gitea-port-4000-and-localhost-forward.md) | Gitea on port 4000 in-cluster, localhost forward, fncli host translation | One stored URL works for pods and host tooling. |
| [0020](0020-tilt-dev-loop.md) | Tilt dev loop, with the tilt-run image for run pods | Live update for the code servers and a rebuilt run image for run pods. |
| [0021](0021-webserver-owns-the-record-and-the-rules.md) | Responsibility: the webserver owns the record and the rules; Dagster carries out decisions | Dagster asks and acts; decisions come back as typed outcomes; the launcher follows it. |
