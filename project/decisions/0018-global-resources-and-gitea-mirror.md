# 0018. Global resources assigned to projects, and a Gitea mirror of GitHub (design note)

- Status: Superseded. The schema names and assignment model are superseded by [0019](0019-global-resources-and-shared-pull-requests.md); the mirror design is superseded by [0020](0020-gitea-mirror-service.md).

## Context

Secrets, repositories and datasets are scoped to one project ([0003](0003-project-scoped-git-repositories.md), [0004](0004-secrets-and-secret-providers.md)). That keeps credentials apart, but it means the same upstream repository or credential used by two projects is registered twice, and a data controller cannot grant a project access to a resource they own once.

The wish that started this: track a GitHub repository, including its merged pull requests, in the node's own Gitea, over outbound-only connections, so the sensors read from Gitea. The sensors already support Gitea ([0005](0005-git-api-protocol-and-factory.md)), and polling GitHub directly stays the beta behaviour ([0006](0006-github-ingest-pulls-endpoint.md)).

Private upstream repositories rule out a simple shared mirror: the mirror needs a token that can read the repository, and projects must not be able to read each other's private repositories through it.

## Decision

### 1. Global resources, used by projects

Make the resources global and give projects a row that says what they do with each one.

Global, owned by the data controller, no `project_id`:

- `Secret`: `key` (unique, immutable), `namespace`, `provider`, `description`.
- `Repository`: `uri` (unique), `provider`, `api_uri`, `secret_id`, and an optional `mirror_uri` that the sensors use when set.
- `Dataset`: `name` (unique), connection fields as today, `secret_id`.

Per project, carrying that project's own configuration:

- `TriggerSource`: `project_id`, `repository_id`, `watch_dir`, `base_branch`, `initial_cursor`. Unique on `(project_id, repository_id)`. Pull request triggers hang off it, so cursors and `uq_pr_repo_number` stay per project.
- `ResultsDestination`: `project_id`, `repository_id`, `target_dir`, `owned_by_federated_node`. One per project, as today.
- `DatasetAccess`: `project_id`, `dataset_id`. Unique on `(project_id, dataset_id)`.

Foreign keys repointed: `projects.default_dataset_id` and `tasks.dataset_id` to `dataset_access`; the pull request trigger and result references to `trigger_sources` and `results_destinations`. `triggers`, `tasks.project_id`, `results_backends` and `whitelisted_images` are unchanged.

The assignment row is the permission boundary: a project can use a repository, dataset or the secret behind it only through a row the controller created. Projects never reference a secret directly.

### 2. `enabled` and `revoked` on each assignment

Each of `TriggerSource`, `ResultsDestination` and `DatasetAccess` has two booleans:

- `enabled`: a person deliberately turned the resource on or off for the project.
- `revoked`: the system withdrew access, because the controller revoked the grant or deleted the global resource or secret it depends on.

A resource is active when `enabled` and not `revoked`. Revoking sets only `revoked`; it does not touch `enabled`, so a re-grant clears `revoked` and restores the previous state without overriding an admin's manual disable.

Revocation is per resource. It never disables the project; the rest of it keeps running, and the project health check reports the revoked resource. Sensors and task launch skip inactive resources.

### 3. The API stays flat

The backend joins an assignment to its global row and returns today's trigger and results repository shapes (`uri`, `api_uri`, `watch_dir`, `base_branch`, cursor, secret reference), with `uri` taken from `mirror_uri` when set. The sensors and the DTOs they read do not change.

### 4. Gitea mirror (parked)

A separate, self-contained service with no dependency on Dagster or the webserver:

- Outbound only. It polls GitHub (conditional requests, `updated_at` cursor) and fetches branches and `refs/pull/*/head`. It pushes to a normal Gitea repository, not a Gitea pull mirror, which I expect cannot hold pull requests; verify.
- Scope: merged pull requests into the base branch. For each: create a `pr/<n>` branch, open a Gitea pull request, and mark it merged with `manually-merged` at GitHub's `merge_commit_sha`. No comments, reviews or open pull requests.
- One mirror per global `Repository`. Which projects may read it is exactly the set of `TriggerSource` rows for it.
- The upstream token is the repository's secret. The service reads it from the Kubernetes secret by reference (`namespace`, `key`) and passes it to git through an HTTP header, not the remote URL. Its service account needs `get` on only those secrets.
- Authors: a shadow Gitea user named after the GitHub login, so `raised_by` matches upstream.
- The sensors then need only `mirror_uri` set on the repository.

## Consequences

- One copy and one credential per upstream repository, however many projects use it, and one place to rotate it.
- The schema change is a split migration: de-duplicate global rows by `uri` or `name`, create assignment rows, repoint the foreign keys, drop the old columns. It touches the webserver models, API, fncli and tests. [0013](0013-baseline-migration-edited-in-place.md) allows editing the baseline in place while no deployment holds data, which makes this much cheaper to do before one does.
- Two FK columns are renamed (`trigger_repository_id`, `results_repository_id`); the API can keep the old names to avoid touching the DTOs.
- Controller-only authorization is needed to create global resources and grants. It belongs with the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).
- Shared credentials mean shared audit trail and rate limits.
- Not required for beta. Until it lands, the beta keeps one registration per project and polls GitHub directly.

## Open items

- Whether `whitelisted_images` should follow the same pattern.
- What a task does when it needs a dataset whose access is inactive: skip with a reason, or fail.
- Who creates the per-project Gitea read user and token for the mirror, and where the token is stored.
- Untested Gitea behaviour the mirror depends on, to check with a spike: the pull request files endpoint on a `manually-merged` pull request, `manually-merged` with squash and rebase merges, and `merged_at` being the sync time rather than GitHub's.
- Real-time updates are not a requirement. If wanted later, a Gitea webhook to the webserver on mirror sync is the in-cluster route.

## Alternatives considered

- **One mirror per project, keyed by project id** (a Gitea org per project): isolates private repositories with no schema change, at the cost of duplicate mirrors. It is the fallback if the schema change is deferred.
- **Shared mirror gated by a GitHub entitlement check** (a project's own token must be able to read the repository): rejected for a controller-granted assignment, which is simpler and does not store project tokens.
- **Secrets with several `project_id`s** (a join table, or an `admin_secrets` table beside `project_secrets`): covers shared secrets but leaves repositories and datasets duplicated.
- **A `disabled_reason` string** instead of `revoked`: rejected, there is one reason.
- **Argo CD** to mirror: it syncs git refs into a cluster and sees no pull request objects, so it does not solve this.
- **Webhooks from GitHub to the node**: not needed; the mirror keeps the node outbound-only.
