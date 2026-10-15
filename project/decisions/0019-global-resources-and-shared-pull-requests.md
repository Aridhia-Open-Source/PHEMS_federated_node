# 0019. Global resources assigned to projects, with pull requests stored once per repository

- Status: Proposed (not built; not required for beta). Reviewed against `origin/dagster-develop-preview`, see [the review](../handover/moonshot-review.md).
- Supersedes the schema naming in [0018](0018-global-resources-and-gitea-mirror.md). The Gitea mirror is [0020](0020-gitea-mirror-service.md) and depends on this.

## Context

Secrets, repositories and datasets belong to one project ([0003](0003-project-scoped-git-repositories.md), [0004](0004-secrets-and-secret-providers.md)). A repository or credential used by two projects is registered twice, each project polls the git provider for it separately, and each stores its own copy of every pull request. A data controller cannot grant a project access to something once.

## Decision

### 1. Global resources, with a per-project assignment

Global, created by the data controller, no `project_id`:

| Table | Columns |
|---|---|
| `secrets` | `id`, `key`, `namespace`, `provider`, `label` (unique), `description` |
| `trigger_repositories` | `id`, `uri`, `provider`, `api_uri`, `secret_id` |
| `results_repositories` | `id`, `uri`, `provider`, `api_uri`, `secret_id` |
| `datasets` | `id`, `name`, `host`, `port`, `type`, `read_schema`, `write_schema`, `extra_connection_args`, `secret_id` |

Per project, holding that project's own configuration:

| Table | Columns |
|---|---|
| `project_trigger_repositories` | `id`, `project_id`, `trigger_repository_id`, `watch_dir`, `base_branch`, `initial_cursor`, `enabled`, `revoked` |
| `project_results_repositories` | `id`, `project_id`, `results_repository_id`, `target_dir`, `owned_by_federated_node`, `enabled`, `revoked` |
| `project_datasets` | `id`, `project_id`, `dataset_id`, `enabled`, `revoked` |

A project reaches a repository or dataset only through its own assignment row. Projects never reference a secret; the credential belongs to the global resource. `datasets.name` is already globally unique, so de-duplicating datasets by name is a no-op for existing data.

### 2. `enabled` and `revoked`

- `enabled`: a person turned the resource on or off for the project.
- `revoked`: the controller withdrew the project's access.

An assignment is **active** when `enabled` and not `revoked`. Revoking sets only `revoked`, never `enabled`, so a re-grant clears `revoked` and restores the previous state. Revoking affects only that resource; the project keeps running.

**Visibility contract.** The flat list and by-id endpoints return inactive assignments too, with `enabled`, `revoked` and a computed `active`. Hiding them breaks in-flight work in Dagster: results delivery unpacks `(repository,) = ...` on the project's results repository (`dagster/app/backend.py:189`), `_find_pull_request` in `delivery/results.py` looks up the task's trigger repository through the list, and the results sync sensor resolves a result's repository by id (`pull_request_sync.py:276`). So the ingest, evaluate and launcher sensors filter on `active`, while delivery and results sync keep resolving inactive rows by id. A delivery that cannot proceed should fail with a recorded error, not an unpack `ValueError`.

### 3. Pull requests stored once per repository

- New `pull_requests`: the provider's facts, shared by every project: `id`, `trigger_repository_id` (global), `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`. Unique on `(trigger_repository_id, number)`. Replaces `uq_pr_repo_number`.
- `pull_request_triggers` stays per project and keeps the evaluation state (`state`, `state_cause` and `project_id` via `Trigger`, `spec_raw`, `task_id`). It gains `pull_request_id` and `project_trigger_repository_id` (replacing `trigger_repository_id`) and drops the duplicated facts; `title`, `raised_by` and `requested_by` become properties through `pull_request`. Unique on `(project_trigger_repository_id, pull_request_id)`. `Trigger.project_id`, `Task.project_id` and the unique `Task.trigger_id` are unchanged.
- **Fan-out:** when a pull request is stored, the backend creates a trigger for each active `project_trigger_repositories` row on that repository.
- **Upsert:** the batch ingest endpoint (`trigger_repositories_api.py:243-265`) currently turns any `IntegrityError` into a 400 for the whole batch. With shared storage it must become an upsert plus fan-out, even if only storage is deduplicated, because a second project's tick re-sends PRs already stored.
- **Two cursors.** The global poll cursor is the max `merged_at` of `pull_requests` for the repository. An assignment's cursor is where its fan-out starts: when a project is added to a repository it starts at the latest stored pull request, so history is not replayed. `initial_cursor` stays as an optional override to start earlier. Both are exposed on the flat DTO (`pr_cursor` per assignment, plus the global one).
- **Backfill.** Fan-out only runs when a pull request is stored, so it is not enough on its own. When an assignment is created, re-enabled or un-revoked, or its `initial_cursor` is set earlier than its starting point, the backend backfills triggers from `pull_requests` for the PRs it missed. Polling the provider cannot satisfy an earlier `initial_cursor` because the global cursor is already ahead.
- **Delete semantics.** Today `pull_request_triggers.trigger_repository_id` is `ON DELETE CASCADE` and deletes only the child row, leaving the `triggers` parent and its `tasks.trigger_id` (RESTRICT) as an orphan. For `project_trigger_repositories` use RESTRICT while triggers exist.
- `pr_count` and the healthcheck count stay per assignment.

### 4. Ingest

Ingest polls once per global trigger repository, using that repository's own secret. The existing sensor iterates the flat per-project list, so this is a real sensor change, an endpoint change and a DTO addition: the flat trigger-repository DTO carries the global repository id (`trigger_repository_id`) beside its `id`, and the batch endpoint takes the global id. The sensor groups the flat list by global id, polls once per group, and posts the batch to the global endpoint. The other PR endpoints stay keyed on the assignment id.

### 5. The flat API

The backend joins an assignment to its global row and returns today's repository shape. The corrections from the review:

- The flat `id` is the **assignment id**. Every Dagster PR, task and results call is keyed on it (`/trigger_repositories/<id>/pull_requests/...`, `get_results_repository_by_id`, the evaluate job tag in `pr_evaluate.py:174`).
- `project_id` is the assignment's project. Dagster's repository and dataset models keep requiring it.
- New fields: the global `trigger_repository_id`, and `enabled`, `revoked` and `active` on trigger repository, results repository and dataset DTOs.
- Dagster's nested `Secret` model (`dagster/app/models/secret.py:24-25`) requires `project_id` and `label`. Dagster reads only `key`, `namespace` and `provider`, so make those two optional or remove them. `scripts/fncli` has its own copies of these models with the same edit.
- `GET /results_repositories?project_id=` returns exactly one item per project today. Decide what it returns when that assignment is inactive (see below).

So Dagster does change, but in DTOs and a few sensor filters, not in its structure.

### 6. Datasets

- `tasks` reach a dataset through `task_specs.dataset_id`, and `projects.default_dataset_id` points at `datasets.id`. Both keep pointing at `datasets.id`; no repoint.
- The check "the dataset belongs to this project" (`Task.validate`, `models/task.py:128`; `Project.resolve_dataset`, `models/project.py:95-101`; `NewTaskDTO.from_spec`) becomes "this project has an active `project_datasets` row for it".
- `default_dataset_id` is not tied to an assignment today (`task.py:138`, `project.py:101`, `TriggerRepository.dataset`), so a default can be unassigned or revoked and tasks would still run on it. Make it a composite FK `(project_id, default_dataset_id)` to `project_datasets(project_id, dataset_id)` and check `active` in `resolve_dataset`. This also removes the `projects`/`datasets` FK cycle and its `post_update` workaround.
- `Dataset.add` makes the first dataset in a project its default (`models/dataset.py:87-97`); that logic moves to assignment creation.
- The launcher's `GET /datasets/<id>` (`launcher.py:216`) is not project-aware. It needs a project-aware lookup, or the active flag in the response.
- `task_specs.dataset_id` is `ON DELETE CASCADE` and `tasks.task_spec_id` cascades from `task_specs` (`001_baseline.py:221-247`), so deleting a dataset deletes the tasks that ran on it. Change both to RESTRICT or SET NULL.
- Datasets API: the `?project_id=` filter becomes a join, POST no longer requires `project_id`, PATCH no longer moves it. `DatasetDTO.project_id` has no single value for a global dataset: omit it and make it optional in Dagster, or return the caller's `?project_id=` context.

### 7. Secrets

- The API moves from `/projects/<id>/secrets` to `/secrets`. `Secret.get_in_project` becomes `get_by_label`. `label` is unique globally, because every repository and dataset POST/PATCH and fncli address secrets by `secret_label`.
- `Secret.key` is currently `"<project_id>-<label>"`; it needs a new generation rule, still a valid DNS subdomain (#543 validates it).
- The composite FKs `(project_id, secret_id)` and `UNIQUE(project_id, id)` go. Delete checks the global resources' usage only.
- Rotating a secret affects every project using it, by design, and stays exempt from the project lock.
- `delete_project` deletes the project's assignments only. It must not delete secrets, datasets or repositories, and must not call `SecretProvider.delete`.

### 8. Results

- `UNIQUE(project_id)` moves to `project_results_repositories` ("one per project for now" is kept).
- `results.results_repository_id` repoints to the assignment, so each project's delivered PRs are tracked against its own assignment. `(task_id, results_repository_id)` stays unique.
- `Project.in_flight_task_ids` already counts exactly the tasks that need the assignment (SUCCESS without a result, `IN_PROGRESS` delivery). Revoke is a system action and does not require the project locked, yet it breaks those deliveries. Minimum: keep returning the revoked row, and make delivery fail with a recorded error. Whether revoke is blocked while work is in flight, or the failed-delivery outcome is accepted, is a decision (below).

### 9. Other places that change

- `check_no_loop(project_id, uri)` (`helpers/repository_loop.py:378-398`) joins trigger and results repositories by `(project_id, uri)` and must move to the assignment tables, where `watch_dir` and `target_dir` live. Cross-project loops (one project's results repository is another's trigger repository) become possible because `uri` is global; whether to forbid them is a decision.
- `DAR.__init__` derives `project_id` from `dataset.project_id` (`models/extras/dar.py:67`). It is disconnected code but will break silently; pass the project in.
- Editing or deleting a global dataset, repository or secret affects every assigned project. Today the `require_drained(project)` lock guards a single project. The rule needs defining (below).

### 10. Migration

ADR [0013](0013-baseline-migration-edited-in-place.md) says the baseline is edited in place, but `webserver/migrations/versions/002_result_step_state_project_lock.py` already exists on the preview branch (#548). Either fold 002 and this change into the baseline, or freeze 001 and add 003. Do not mix. Migration is a split: each current table becomes its global part (de-duplicated by `uri` or `name`) and an assignment row.

## Consequences

- One credential, one set of pull requests and one provider poll per repository, however many projects use it.
- Each project keeps its own state, results and cursors, so projects stay independent.
- The controller's grant is the assignment row; revoking it stops only that connection.
- About 6–8k changed lines across roughly 90 files: ~1,400 non-test webserver lines rewritten and 700–900 new, Dagster ~100–150, fncli ~500, tests ~3,000+, openapi and docs ~1,500. The chart is untouched.
- Creating global resources and grants needs a controller-only permission; that belongs with the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).
- Heavy overlap with open PRs #548, #547, #543, #534, #531 and #535; light overlap with #526, #533, #529, #530; independent: #528, #532, #544, #545, #546.
- Supersedes or amends ADRs 0003, 0004, 0001, 0006, 0007, 0009, 0013 and 0015, and `docs/architecture/entities.md`.

## Decisions still needed

1. **Revoke versus in-flight work.** Block revoke while the project has in-flight tasks or deliveries for that assignment, or accept failed deliveries with a recorded error.
2. **Drain rule for global edits.** Which projects must be locked and drained to edit or delete a global dataset, repository or secret: all assigned projects, or an explicit exemption like secret rotation.
3. **Cross-project loops** (a project's results repository being another's trigger repository): forbid or allow.
4. **`GET /results_repositories?project_id=` for an inactive assignment:** return it with the flags, or an empty list.
5. **`DatasetDTO.project_id`** for a global dataset: omit it or return the caller's context.
6. **Migration policy:** fold 002 into the baseline or freeze 001 and add 003.
7. **Controller authorization:** who may create global resources and grants, and how it ties into the authorization rework.
8. Whether `whitelisted_images` follows the same pattern.

## Implementation order

Each stage leaves the webserver tests runnable.

0. Pin the flat contract (below). No behaviour change.
1. Global secrets: drop `project_id`, unique `label`, drop the composite FKs, `/secrets`, the three `secret_label` resolvers, `SecretDTO`; Dagster `Secret` model; fix `delete_project`.
2. Global datasets plus `project_datasets`: assignment model and endpoints, `resolve_dataset`, `Task.validate`, the default-dataset composite FK, the cascade to RESTRICT, DAR; fncli dataset helpers.
3. Global results repositories plus `project_results_repositories`: repoint `results`; flat list and by-id return assignment-joined rows including inactive ones; healthcheck; loop check for results.
4. Global trigger repositories plus `project_trigger_repositories`: flat `id` is the assignment id; complete the loop check; `pr_cursor`, `pr_count`, `dataset_id` per assignment.
5. `pull_requests`, fan-out, the upsert batch endpoint, and backfill on create, enable and un-revoke.
6. `enabled` and `revoked` behaviour in the sensors, launcher and delivery (decisions 1 and 4).
7. The ingest sensor polls once per global repository.
8. fncli, `openapi.json`, `docs/architecture`, ADR updates.

Stages 1–4 are mostly mechanical. Decisions 1–5 must be settled before stages 5–6.

## Contract tests to add first

Assert exact key sets and types, not just status codes:

1. `GET /trigger_repositories` and `/<id>`: keys `id, uri, provider, api_uri, secret{...}, watch_dir, base_branch, project_id, dataset_id, initial_cursor, pr_cursor, pr_count`; `pr_cursor` is `initial_cursor` with no PRs and the max `merged_at` after; the `?project_id=` and `?project_enabled=true` filters.
2. PR endpoints keyed by `(repo_id, number)`: list (paged, `state` filter), get, patch state, `/task` (201 then 200 idempotent, 400 on a bad spec with `REJECTED` recorded); batch: 201, and pin that a duplicate number returns 400 today so the upsert change is deliberate.
3. `GET /results_repositories?project_id=` returns exactly one item; `/results_repositories/<id>`; the `/results` round trip including the `step` filter.
4. `GET /datasets`, `/datasets/<id>`, `/datasets/<name>`; `GET /projects` item keys including `default_dataset_id`, `locked`, `enabled`; the task DTO `spec.dataset_id`.
5. Task creation through the API and the PR path both reject a dataset of another project and fall back to the default dataset.
6. The healthcheck body shape.

Plus a cross-service check: the webserver tests dump these responses to a committed JSON fixture and the Dagster and fncli model tests parse the same fixtures. That catches the `Secret.project_id`/`label` breakage at test time.

## Alternatives considered

- **Keep everything project-scoped** (today): isolated, but repeated registration, polling, credentials and stored pull requests.
- **Pull requests per assignment only:** no sharing of provider facts; simpler, but the duplication stays.
- **A `disabled_reason` string** instead of `revoked`: rejected, there is one reason.
- **Secrets with several `project_id`s**, or `admin_secrets` beside `project_secrets`: covers shared secrets but leaves repositories and datasets duplicated.
