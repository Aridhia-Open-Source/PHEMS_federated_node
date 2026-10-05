# Project-scoped repositories, secrets and results delivery

**Status:** design agreed 2026-09-30, **not implemented**.
**Build order:** Stage 1 (DB + API), then Stage 2 (Dagster).

Supersedes `projects.results_repository_id` and the DVC-first delivery in
[DVC_GITEA_RESULTS_PLAN.md](DVC_GITEA_RESULTS_PLAN.md). **DVC is dropped for the initial beta and
returns shortly after**, so don't build anything that blocks adding it.

## Why

- Trigger repos are globally unique by `uri`; a results repo can be shared by any project
  (non-unique FK). Neither was a deliberate choice.
- Secrets are global: no owner, and one project can reference another project's secret.
- Projects may need different credentials for the same remote, so nothing is shared. A project
  owns its rows and the same remote is added once per project.

## Settled decisions

### Repositories
- Scoped to a project, unique on `(project_id, uri)`. Same remote in many projects = add it
  once per project, each with its own secret, cursor and pull requests.
- Many trigger repos per project (already true). Results repos: **one per project to start**,
  behind a named unique constraint and a single accessor so it can grow later.
- `TriggerRepository` and `ResultsRepository` share a base: `project_id`, `uri` (scheme
  stripped), `provider`, `api_uri`, stored repo path, secret reference, `check_connection()`.
  `ResultsRepository` mirrors `TriggerRepository`, with its own `/results_repositories`
  endpoints and a `target_dir` (mirrors `watch_dir`).
- Repo path is stored at creation (`owner/repo`, `group/sub/project`), not derived from `uri`.
  API-path building moves onto `GitProvider`.
- `projects.results_repository_id` is dropped; the repo carries `project_id`.

### Secrets
- `Secret` is a generic secret reference: `project_id`, project-local `name`, `secret_type` (only `K8S`
  for now; another secret store is another value) and `store_name`, derived as `{project_id}-{name}`
  for `K8S` (the real cluster secret). `UNIQUE(project_id, name)`, `UNIQUE(store_name)`, `UNIQUE(project_id, id)`.
- Children reference the secret **by id** with a composite FK `(project_id, secret_id)`, so the
  database rejects another project's secret. The neutral column is `store_name`, not `key`.
- Secrets API is nested under the project and addressed by name: `/projects/<project_id>/secrets[/<name>]`
  (decided in review of #429; replaces `project_id` in the body and the `/secrets` path). Keep Kubernetes
  out of API names: children carry `secret_name` and `secret_type`. Dagster picks its reader by
  `secret_type` and, for `K8S`, reads the cluster secret directly by `secret_store_name`; task pods use
  `envFrom` by that name.
- Authorization is out of scope: a colleague is reworking Keycloak and the auth decorators. Don't design
  per-project permissions here.

### Results delivery (local-first, raw git)
- A task succeeds once its results are committed to the **local Gitea** (a project-owned,
  always-present destination).
- Replication to upstream repos is separate: push the same commit as branch
  `results/task-<id>` and **open a PR unless one exists**. "Delivered" means PR opened, not merged.
- `TaskResult`: one row per `(task, destination)` with status, attempts, branch, commit sha,
  PR number/url, error. `UNIQUE(task_id, results_repository_id)`. Created as a snapshot at
  dispatch; the local row is created as delivered.
- Raw git for the initial beta. DVC returns shortly after. The existing `ResultsBackend` model
  is left untouched and not built on. Keep the delivery step free of assumptions that results
  are always plain files in git, so DVC can slot in.
- Results live under the results repo's `target_dir`, with a subdirectory per trigger repo and
  the trigger metadata in the zipped results.
- **Loop guard:** when a results repo and a trigger repo in a project share a remote, their
  directories must not overlap (neither a prefix of the other) and `watch_dir` must not be
  empty. Validate at creation of either and when `watch_dir` changes.
- Cap the size of delivered results and fail early with a clear error.
- The trigger payload can override the project's default dataset.

## Stage 1: DB and API

**DB** (fold into `001_baseline`, fresh DB)
1. `secrets`: add `project_id`, `store_name` and the unique constraints.
2. Shared repo base with the composite secret FK and stored repo path.
3. `trigger_repositories`: use the base; unique `(project_id, uri)`.
4. `results_repositories`: use the base, add `project_id` and `target_dir`; drop
   `projects.results_repository_id`.
5. `datasets`: reference the secret by id with the composite FK.
6. New `task_results` table.

**API**
1. `/projects/<id>/secrets[/<name>]`: store secret created under `store_name`, by `secret_type`;
   409 while referenced.
2. `/trigger_repositories`: duplicate check on `(project_id, uri)`; resolve secret within the
   project; loop-guard validation.
3. `/results_repositories`: new, mirrors trigger repos.
4. `/projects/<id>/healthcheck`: both repo types; secret read through `store_name`.
5. `GitProvider` API paths; DTOs, OpenAPI, tests and fixtures.
6. Task results: read endpoint(s) only.
7. Follow-on: `fncli` passes `project_id`, reads the token back by `store_name`.

## Stage 2: Dagster (outline only)
- Models and `GitAPIFactory` read secrets through `store_name`.
- Success sensor: results to local Gitea, create the `TaskResult` rows.
- Replication sensor: push branch upstream, find or open the PR, update the row.
- `GitAPI` gains find-PR-by-branch and create-PR for Gitea and GitHub.
- Git in the Dagster image; idempotent pushes; serialise per results repo; retries.

## Parked: revisit when we hit them

| Item | Revisit when |
|---|---|
| `owned_by_federated_node` on `ResultsRepository` (may be answered by "local = owned") | before Stage 2 |
| Delete rules for repos and projects with running tasks | Stage 1 API |
| Named unique constraint and the results-repo accessor | Stage 1 DB |
| Payload dataset override: authorisation beyond the same-project check | touching task request creation |
| `degraded` project health when only some repos fail | touching the healthcheck |
| Many results repos per project (drop `UNIQUE(project_id)`) | after Stage 1 works |
| Required versus best-effort destinations; is "PR opened" enough for task and PR status | Stage 2 design |
| Retry policy and a manual redeliver endpoint | Stage 2 |
| Size cap value; governance of raw results in permanent git history (less of an issue once DVC returns) | before Stage 2 build |
| Retention of the local copy | Stage 2 |
| Confirm Gitea's PR lookup by branch; git CLI in the Dagster image | Stage 2 |
| **DVC returns** (shortly after beta): `ResultsBackend`, moving its plaintext credentials into secrets, reassess the size cap | first item after the beta ships |
| GitLab and Bitbucket API paths | adding a provider |
