# 0019. Global resources assigned to projects, with pull requests stored once per repository

- Status: Accepted (built). This record is now the **umbrella**: the detail lives in [0021](0021-global-resources-and-project-links.md) to [0028](0028-who-owns-what-webserver-record-and-dagster-history.md), one record per major design change from `dagster-develop`. Where this record and those differ, they win: each was written against the code at `moonshot/shared-resources` `c55984fb`.
- The previous long text of this record (sections 1 to 12, implementation order, contract tests) is in git history at `c55984fb`.
- Supersedes the schema naming in [0018](0018-global-resources-and-gitea-mirror.md). The Gitea mirror is [0020](0020-gitea-mirror-service.md) (parked for the beta) and depends on this.

## Context

Secrets, repositories and datasets belonged to one project ([0003](0003-project-scoped-git-repositories.md), [0004](0004-secrets-and-secret-providers.md)). A repository or credential used by two projects was registered twice, each project polled the git provider for it separately, and each stored its own copy of every merged pull request. A data controller could not grant something once, or withdraw it once.

## Decisions

| ADR | Decision | Read it for |
|---|---|---|
| [0021](0021-global-resources-and-project-links.md) | Secrets, datasets, trigger and results repositories are global; a project reaches them only through a link row that holds its own settings | the data model, `/global/...` and `/projects/<pid>/...` URLs, `active`, loops |
| [0022](0022-git-provider-and-repository-identity.md) | A global `GitProvider`; a repository is `provider_id` + `repo_path` + its own secret | identity, URI rules, why `uri` is unique |
| [0023](0023-pull-requests-stored-once-fan-out-and-cursors.md) | Pull requests are stored once per repository and fanned out to the links that match; cursors; switching back on skips the gap (no backfill) | ingest, match rule, `skip_gap` |
| [0024](0024-task-configuration-pinning.md) | A task is pinned to its configuration; a changed setup fails the task at launch or makes its result `STALE` | pinning, replaces lock-and-drain |
| [0025](0025-switching-off-revoking-and-soft-delete.md) | Switching off, revoking (admin, immediate, for good) and soft delete; locked is a pause | the table of what each switch does |
| [0026](0026-state-transition-tables.md) | Allowed moves for triggers, tasks and result steps are tables; the webserver refuses others with 409 | states, `REVOKED`, `STALE` |
| [0027](0027-dagster-pipeline-ops-sensors-and-retries.md) | Ingest is an op; thin sensors; retries; the launcher gate; the 11 sensors | the Dagster side |
| [0028](0028-who-owns-what-webserver-record-and-dagster-history.md) | The webserver owns the record and the rules; Dagster owns run history and calls the webserver; auth is deferred | boundaries, auth gaps |

## Settled decisions and where they went

1. Revoke takes effect immediately; it needs no lock: [0025](0025-switching-off-revoking-and-soft-delete.md).
2. Deleting is a soft delete with no lock or drain: [0025](0025-switching-off-revoking-and-soft-delete.md).
3. Cross-project loops are forbidden: [0021](0021-global-resources-and-project-links.md).
4. Link listings return inactive links with their flags: [0021](0021-global-resources-and-project-links.md).
5. Global datasets have no `project_id`: [0021](0021-global-resources-and-project-links.md).
6. The migration is folded into the baseline: [0013](0013-baseline-migration-edited-in-place.md).
7. Creating global resources and grants uses the admin role for now: [0021](0021-global-resources-and-project-links.md), [0028](0028-who-owns-what-webserver-record-and-dagster-history.md).
8. `whitelisted_images` is not part of this change: [0021](0021-global-resources-and-project-links.md).
9. URL layout: [0021](0021-global-resources-and-project-links.md).
10. Trigger states `UNKNOWN`, `YIELDED`, `REJECTED`; only an `UNKNOWN` trigger of an active link can get a task: [0023](0023-pull-requests-stored-once-fan-out-and-cursors.md), [0026](0026-state-transition-tables.md).
11. `?active=true` and the other query options replace Python filtering in Dagster: [0027](0027-dagster-pipeline-ops-sensors-and-retries.md).
12. A finished task cannot change status: [0026](0026-state-transition-tables.md).
13. `POST /results`: 409 unless the task is `SUCCESS`; revoked gives `REVOKED`, a changed configuration gives `STALE`: [0024](0024-task-configuration-pinning.md), [0025](0025-switching-off-revoking-and-soft-delete.md).
14. A disabled secret is refused (400) on create and patch of repositories and datasets: [0022](0022-git-provider-and-repository-identity.md).
15. **Still to confirm by the owner:** dataset `PATCH` returns 200, and `GET /tasks` clamps `page` and `per_page` below 1.

## Consequences

- One credential, one set of pull requests and one provider poll per repository, however many projects use it.
- Each project keeps its own state, results and cursors, so projects stay independent.
- The controller's grant is the link row; revoking it stops only that connection, and the bulk revoke stops all of them.
- Creating global resources and grants uses the admin role until the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).
- Supersedes or amends [0003](0003-project-scoped-git-repositories.md), [0004](0004-secrets-and-secret-providers.md), [0001](0001-polymorphic-triggers.md), [0006](0006-github-ingest-pulls-endpoint.md), [0007](0007-results-delivered-as-branch-and-pull-request.md), [0009](0009-sync-reconciler-and-operational-rules.md), [0013](0013-baseline-migration-edited-in-place.md) and [0015](0015-fncli-dev-ops-tool.md), and `docs/architecture/entities.md`.
- Known gaps, with their ADRs: [0025](0025-switching-off-revoking-and-soft-delete.md) and [0027](0027-dagster-pipeline-ops-sensors-and-retries.md) list what the code does not do (a deleted dataset link leaves a task `PENDING`; the launcher ignores `locked`).

## Alternatives considered

- **Keep everything project-scoped** (before): isolated, but repeated registration, polling, credentials and stored pull requests.
- **Pull requests per link only:** no sharing of provider facts; simpler, but the duplication stays.
- **A `disabled_reason` string** instead of `revoked`: rejected, there is one reason.
- **Secrets with several `project_id`s**, or `admin_secrets` beside `project_secrets`: covers shared secrets but leaves repositories and datasets duplicated.
