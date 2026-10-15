# 0019. Global resources assigned to projects, with pull requests stored once per repository

- Status: Proposed (not built; not required for beta)
- Supersedes the schema naming in [0018](0018-global-resources-and-gitea-mirror.md). The Gitea mirror is out of scope here.

## Context

Secrets, repositories and datasets belong to one project ([0003](0003-project-scoped-git-repositories.md), [0004](0004-secrets-and-secret-providers.md)). A repository or credential used by two projects is registered twice, each project polls the git provider for it separately, and each stores its own copy of every pull request. A data controller cannot grant a project access to something once.

## Decision

### 1. Global resources, with a per-project assignment

Global, created by the data controller, no `project_id`:

| Table | Columns |
|---|---|
| `secrets` | `id`, `key`, `namespace`, `provider`, `description` |
| `trigger_repositories` | `id`, `uri`, `provider`, `api_uri`, `secret_id` |
| `results_repositories` | `id`, `uri`, `provider`, `api_uri`, `secret_id` |
| `datasets` | `id`, `name`, `host`, `port`, `type`, `read_schema`, `write_schema`, `extra_connection_args`, `secret_id` |

Per project, holding that project's own configuration:

| Table | Columns |
|---|---|
| `project_trigger_repositories` | `id`, `project_id`, `trigger_repository_id`, `watch_dir`, `base_branch`, `initial_cursor`, `enabled`, `revoked` |
| `project_results_repositories` | `id`, `project_id`, `results_repository_id`, `target_dir`, `owned_by_federated_node`, `enabled`, `revoked` |
| `project_datasets` | `id`, `project_id`, `dataset_id`, `enabled`, `revoked` |

A project reaches a repository or dataset only through its own assignment row. Projects never reference a secret; the credential belongs to the global resource.

### 2. `enabled` and `revoked`

- `enabled`: a person turned the resource on or off for the project.
- `revoked`: the controller withdrew the project's access.

An assignment is active when `enabled` and not `revoked`. Revoking sets only `revoked`, never `enabled`, so a re-grant clears `revoked` and restores the previous state. Revoking affects only that resource; the project keeps running. Sensors and task launch use only active assignments. A task's dataset must have an active `project_datasets` row for its project (this replaces the `dataset.project_id == project.id` check); `tasks.dataset_id` and `projects.default_dataset_id` keep pointing at `datasets.id`.

### 3. Pull requests stored once per repository

- New `pull_requests`: the provider's facts, shared by every project: `id`, `trigger_repository_id`, `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`. Unique on `(trigger_repository_id, number)`. Replaces `uq_pr_repo_number`.
- `pull_request_triggers` stays per project and keeps the evaluation state (`state`, `state_cause`, `payload`, `task_id` via `triggers`). It gains `pull_request_id` and `project_trigger_repository_id` (replacing `trigger_repository_id`) and drops the duplicated facts. Unique on `(project_trigger_repository_id, pull_request_id)`.
- Fan-out: when a pull request is stored, the backend creates a trigger for each active `project_trigger_repositories` row on that repository.
- Cursor: when a project is added to a repository, its starting point is the latest stored pull request, so history is not replayed. `initial_cursor` stays as an optional override to start earlier. Afterwards the cursor is the max `merged_at` of that assignment's triggers, as today.

### 4. Ingest

The target is one poll per global trigger repository, using the repository's own secret. Today's ingest sensor iterates the flat per-project list, so that is the one sensor change this design needs. Without it the storage and credential benefits hold and the fewer-calls benefit does not.

### 5. The API stays flat

The backend joins an assignment to its global row and returns today's repository shape (`uri`, `api_uri`, `watch_dir`, `base_branch`, cursor, secret reference), keeping the existing field names. Dagster DTOs and sensors are unchanged apart from the ingest change above.

## Consequences

- One credential, one set of pull requests and (with the sensor change) one provider poll per repository, however many projects use it.
- Each project still has its own state, results and cursor, so projects stay independent.
- The controller's grant is the assignment row; revoking it stops only that connection.
- Migration is a split of each current table into its global part (de-duplicated by `uri` or `name`) and an assignment row, then repointing foreign keys. It touches webserver models, API, fncli and tests. [0013](0013-baseline-migration-edited-in-place.md) allows editing the baseline in place while no deployment holds data, which is cheapest before one does.
- Creating global resources and grants needs a controller-only permission; that belongs with the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).

## Open items

- Do the ingest sensor change, or accept storage dedupe only.
- Whether `whitelisted_images` follows the same pattern.
- What a task does when its dataset is not active: skip with a reason, or fail.

## Alternatives considered

- **Keep everything project-scoped** (today): isolated, but repeated registration, polling, credentials and stored pull requests.
- **Pull requests per assignment only**: no sharing of the provider facts; simpler, but the duplication stays.
- **A `disabled_reason` string** instead of `revoked`: rejected, there is one reason.
