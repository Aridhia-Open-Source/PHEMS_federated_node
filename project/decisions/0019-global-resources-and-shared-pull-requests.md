# 0019. Global resources assigned to projects, with pull requests stored once per repository

- Status: Proposed (not built). This is the current priority: a one-day attempt, with other work, beta included, parked. Reviewed against `origin/dagster-develop-preview`, see [the review](../handover/moonshot-review.md).
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

**Visibility contract.** The project assignment endpoints return inactive assignments too, with `enabled`, `revoked` and a computed `active`. Hiding them breaks in-flight work in Dagster: results delivery unpacks `(repository,) = ...` on the project's results repository (`dagster/app/backend.py:189`), `_find_pull_request` in `delivery/results.py` looks up the task's trigger repository through the list, and the results sync sensor resolves a result's repository by id (`pull_request_sync.py:276`). So the ingest, evaluate and launcher sensors filter on `active`, while delivery and results sync keep resolving inactive rows by id. A delivery that cannot proceed fails with a recorded error, not an unpack `ValueError`.

**Revoke takes effect immediately.** It is not blocked by in-flight work. Deliveries in flight for that assignment fail with a recorded error.

### 3. Pull requests stored once per repository

- New `pull_requests`: the provider's facts, shared by every project: `id`, `trigger_repository_id` (global), `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`, `base_branch` (the PR's target branch), `files_truncated`. Unique on `(trigger_repository_id, number)`. Replaces `uq_pr_repo_number`.
- New `pull_request_files(pull_request_id, path)`: the changed file paths, captured once at ingest together with `base_branch`. A table rather than a JSON array: paths are matched against `watch_dir` prefixes, a table can be indexed and filtered in SQL (backfill is then a plain query), and it needs no JSON operators across Postgres and the test database. The cost is one row per file, bounded by the provider cap below.
- **Provider cap.** GitHub pages the changed-files list and caps it at 3000. Ingest pages through all of it. A PR beyond the cap sets `files_truncated` and is treated as matching every path, because its watched files cannot be ruled out.
- `pull_request_triggers` stays per project and keeps the evaluation state (`state`, `state_cause` and `project_id` via `Trigger`, `spec_raw`, `task_id`). It gains `pull_request_id` and `project_trigger_repository_id` (replacing `trigger_repository_id`) and drops the duplicated facts; `title`, `raised_by` and `requested_by` become properties through `pull_request`. Unique on `(project_trigger_repository_id, pull_request_id)`. `Trigger.project_id`, `Task.project_id` and the unique `Task.trigger_id` are unchanged.
- **Fan-out:** when a pull request is stored, the backend creates a trigger for every active `project_trigger_repositories` row on that repository. It decides the match from stored data alone: the assignment's `base_branch` against `pull_requests.base_branch`, and its `watch_dir` against `pull_request_files.path` (or `files_truncated`). A matching trigger starts in its normal initial state. A non-matching one is created as `IGNORED`. No provider call is made, so evaluate never calls the provider for a PR the project does not watch.
- **No re-processing.** `pull_requests` is unique on `(trigger_repository_id, number)` and written by upsert, the global cursor only moves forward, and triggers are unique on `(assignment, pull_request)`. Re-sending a PR changes nothing.
- **Config changes.** When an assignment's `watch_dir` or `base_branch` changes, matching runs forward from its cursor only. Older PRs are replayed only if `initial_cursor` is set earlier.
- **Upsert:** the batch ingest endpoint (`trigger_repositories_api.py:243-265`) currently turns any `IntegrityError` into a 400 for the whole batch. With shared storage it must become an upsert plus fan-out, even if only storage is deduplicated, because a second project's tick re-sends PRs already stored.
- **Two cursors.** The global poll cursor is the max `merged_at` of `pull_requests` for the repository. An assignment's cursor is where its fan-out starts: when a project is added to a repository it starts at the latest stored pull request, so history is not replayed. `initial_cursor` stays as an optional override to start earlier. The assignment DTO exposes its cursor (`pr_cursor`); the global repository DTO exposes the global one.
- **Backfill.** Fan-out only runs when a pull request is stored, so it is not enough on its own. When an assignment is created, re-enabled or un-revoked, or its `initial_cursor` is set earlier than its starting point, the backend backfills triggers from `pull_requests` and `pull_request_files` for the PRs it missed, with the same match rule. It is a database-only operation; polling the provider could not satisfy an earlier `initial_cursor` anyway because the global cursor is already ahead.
- **Delete semantics.** Today `pull_request_triggers.trigger_repository_id` is `ON DELETE CASCADE` and deletes only the child row, leaving the `triggers` parent and its `tasks.trigger_id` (RESTRICT) as an orphan. For `project_trigger_repositories` use RESTRICT while triggers exist.
- `pr_count` and the healthcheck count stay per assignment.

### 4. API and Dagster sensors

There is no flat compatibility API. The API exposes the real model.

Global resources, `id` is the resource id:

- `GET /trigger_repositories`, `/results_repositories`, `/datasets`, `/secrets` (and by id).

Project assignments, with the global resource nested:

- `GET /projects/<id>/trigger_repositories`, `/results_repositories`, `/datasets`. Each item carries the assignment's own fields (`watch_dir`, `base_branch`, cursor, `enabled`, `revoked`, `active` for trigger repositories; `target_dir` for results repositories) and the global resource nested. Inactive assignments are returned with their flags.

Pull requests:

- Facts on the global repository: `/trigger_repositories/<id>/pull_requests` (the batch ingest, upsert plus fan-out).
- Per-project evaluation addressed by assignment, for example `/project_trigger_repositories/<id>/triggers`.

Dagster sensors use these directly:

- **Ingest** loops over global trigger repositories and polls each once, with the repository's own secret. It no longer groups a flat list.
- **Evaluate and launch** loop over active assignments and their triggers.
- **Delivery** uses the task's results assignment.
- The evaluate job tag (`pr_evaluate.py:174`) and the task and `/results` calls are keyed on the assignment id.

Dagster's nested `Secret` model (`dagster/app/models/secret.py:24-25`) requires `project_id` and `label`. Dagster reads only `key`, `namespace` and `provider`, so make those two optional or remove them. Dagster's repository and dataset models split into a global model and an assignment model. `scripts/fncli` has its own copies of these models and gets the same changes.

### 5. Results repository lookups

`GET /projects/<id>/results_repositories` returns one item today (one per project). It keeps returning the project's assignment when it is inactive, with its flags, rather than an empty list.

### 6. Datasets

- `tasks` reach a dataset through `task_specs.dataset_id`, and `projects.default_dataset_id` points at `datasets.id`. Both keep pointing at `datasets.id`; no repoint.
- The check "the dataset belongs to this project" (`Task.validate`, `models/task.py:128`; `Project.resolve_dataset`, `models/project.py:95-101`; `NewTaskDTO.from_spec`) becomes "this project has an active `project_datasets` row for it".
- `default_dataset_id` is not tied to an assignment today (`task.py:138`, `project.py:101`, `TriggerRepository.dataset`), so a default can be unassigned or revoked and tasks would still run on it. Make it a composite FK `(project_id, default_dataset_id)` to `project_datasets(project_id, dataset_id)` and check `active` in `resolve_dataset`. This also removes the `projects`/`datasets` FK cycle and its `post_update` workaround.
- `Dataset.add` makes the first dataset in a project its default (`models/dataset.py:87-97`); that logic moves to assignment creation.
- The launcher's `GET /datasets/<id>` (`launcher.py:216`) is not project-aware. It needs a project-aware lookup, or the active flag in the response.
- `task_specs.dataset_id` is `ON DELETE CASCADE` and `tasks.task_spec_id` cascades from `task_specs` (`001_baseline.py:221-247`), so deleting a dataset deletes the tasks that ran on it. Change both to RESTRICT or SET NULL.
- Global datasets have no `project_id`. `/datasets` lists global datasets; a project's datasets are `/projects/<id>/datasets`. POST no longer takes `project_id`, PATCH no longer moves it, and `DatasetDTO` has no `project_id`.

### 7. Secrets

- The API moves from `/projects/<id>/secrets` to `/secrets`. `Secret.get_in_project` becomes `get_by_label`. `label` is unique globally, because every repository and dataset POST/PATCH and fncli address secrets by `secret_label`.
- `Secret.key` is currently `"<project_id>-<label>"`; it needs a new generation rule, still a valid DNS subdomain (#543 validates it).
- The composite FKs `(project_id, secret_id)` and `UNIQUE(project_id, id)` go. Delete checks the global resources' usage only.
- Rotating a secret affects every project using it, by design, and stays exempt from the project lock.
- `delete_project` deletes the project's assignments only. It must not delete secrets, datasets or repositories, and must not call `SecretProvider.delete`.

### 8. Results

- `UNIQUE(project_id)` moves to `project_results_repositories` ("one per project for now" is kept).
- `results.results_repository_id` repoints to the assignment, so each project's delivered PRs are tracked against its own assignment. `(task_id, results_repository_id)` stays unique.
- `Project.in_flight_task_ids` already counts exactly the tasks that need the assignment (SUCCESS without a result, `IN_PROGRESS` delivery). Revoke is a system action and does not require the project locked, yet it breaks those deliveries. Minimum: keep returning the revoked row, and make delivery fail with a recorded error. Revoke is not blocked; the delivery fails with a recorded error (section 2).

### 9. Other places that change

- `check_no_loop(project_id, uri)` (`helpers/repository_loop.py:378-398`) joins trigger and results repositories by `(project_id, uri)` and must move to the assignment tables, where `watch_dir` and `target_dir` live. Cross-project loops (one project's results repository being another's trigger repository) become possible because `uri` is global, and are forbidden: the check runs across projects.
- `DAR.__init__` derives `project_id` from `dataset.project_id` (`models/extras/dar.py:67`). It is disconnected code but will break silently; pass the project in.
- Editing or deleting a global dataset, repository or secret affects every assigned project. It requires every assigned project to be locked and drained (today `require_drained(project)` guards one project). Secret rotation stays exempt.
- Creating global resources and grants requires the admin role for now; revisit with the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).
- `whitelisted_images` does not follow this pattern for now.

### 10. Migration

Fold 002 (`webserver/migrations/versions/002_result_step_state_project_lock.py`, #548) and this change into the baseline, per ADR [0013](0013-baseline-migration-edited-in-place.md): the line is unreleased. If existing data needs carrying, the split is: each current table becomes its global part (de-duplicated by `uri` or `name`) and an assignment row.

### 11. Decisions settled

1. Revoke takes effect immediately; in-flight deliveries fail with a recorded error (section 2).
2. Editing or deleting a global dataset, repository or secret requires every assigned project locked and drained; secret rotation stays exempt (section 9).
3. Cross-project loops are forbidden (section 9).
4. `GET /projects/<id>/results_repositories` returns inactive assignments with their flags (section 5).
5. Global datasets have no `project_id` (section 6).
6. Migration: fold 002 and this change into the baseline (section 10).
7. Creating global resources and grants: admin role for now; revisit with the authorization rework (section 9).
8. `whitelisted_images`: not now (section 9).

## Consequences

- One credential, one set of pull requests and one provider poll per repository, however many projects use it.
- Each project keeps its own state, results and cursors, so projects stay independent.
- The controller's grant is the assignment row; revoking it stops only that connection.
- About 6–8k changed lines across roughly 90 files: ~1,400 non-test webserver lines rewritten and 700–900 new, tests ~3,000+, openapi and docs ~1,500. The chart is untouched. Without a flat layer the model change is larger: Dagster ~250–400 lines (split global and assignment models, new endpoints) and fncli ~600–800. The sensors get simpler, since nothing groups or translates ids.
- Creating global resources and grants uses the admin role until the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).
- Changed paths are fetched once per PR at ingest (paged), and no later per-project provider call is made for unwatched PRs.
- Heavy overlap with open PRs #548, #547, #543, #534, #531 and #535; light overlap with #526, #533, #529, #530; independent: #528, #532, #544, #545, #546.
- Supersedes or amends ADRs 0003, 0004, 0001, 0006, 0007, 0009, 0013 and 0015, and `docs/architecture/entities.md`.

## Implementation order

Each stage leaves the webserver tests runnable.

0. Contract tests (below): pin the unchanged endpoints; write the target shapes as strict `xfail` tests. No behaviour change.
1. Global secrets: drop `project_id`, unique `label`, drop the composite FKs, `/secrets`, the three `secret_label` resolvers, `SecretDTO`; Dagster `Secret` model; fix `delete_project`.
2. Global datasets plus `project_datasets`: assignment model and endpoints, `resolve_dataset`, `Task.validate`, the default-dataset composite FK, the cascade to RESTRICT, DAR; fncli dataset helpers.
3. Global results repositories plus `project_results_repositories`: repoint `results`; `/projects/<id>/results_repositories` includes inactive assignments; healthcheck; loop check for results.
4. Global trigger repositories plus `project_trigger_repositories`: assignment endpoints; complete the cross-project loop check; cursor, `pr_count`, `dataset_id` per assignment.
5. `pull_requests`, `pull_request_files`, fan-out with `IGNORED`, the upsert batch endpoint, and backfill on create, enable and un-revoke.
6. `enabled` and `revoked` behaviour in the sensors, launcher and delivery.
7. The Dagster sensors on the new endpoints: ingest per global repository, evaluate and launch per active assignment, delivery by the task's results assignment.
8. fncli, `openapi.json`, `docs/architecture`, ADR updates.

Stages 1–4 are mostly mechanical. The decisions in section 11 are settled.

## Contract tests to add first

Assert exact key sets and types, not just status codes. Stage 0 does two things.

**Pin what does not change shape:** the PR endpoints keyed by `(repo_id, number)` (list paged with `state` filter, get, patch state, `/task` 201 then 200 idempotent and 400 on a bad spec with `REJECTED` recorded); the `/results` round trip including the `step` filter; `GET /datasets/<name>`; `GET /projects` item keys including `default_dataset_id`, `locked`, `enabled`; the task DTO `spec.dataset_id`; the healthcheck body shape; task creation through the API and the PR path both rejecting a dataset of another project and falling back to the default dataset. Batch ingest: 201, and pin that a duplicate number returns 400 today so the upsert change is deliberate.

**Write the target shapes for changing endpoints as tests marked `xfail(strict=True)`:** global `GET /trigger_repositories` (`id` is the resource id), `GET /projects/<id>/trigger_repositories` and the results repository and dataset equivalents with the nested global resource and assignment fields, `/secrets`, PR ingest on the global repository, and fan-out with `IGNORED`. Each stage removes the marker from the tests it makes pass. A strict `xfail` that unexpectedly passes fails the run, so the flip cannot be forgotten.

Plus a cross-service check: the webserver tests dump these responses to a committed JSON fixture and the Dagster and fncli model tests parse the same fixtures. That catches the `Secret.project_id`/`label` breakage at test time.

## Alternatives considered

- **Keep everything project-scoped** (today): isolated, but repeated registration, polling, credentials and stored pull requests.
- **Pull requests per assignment only:** no sharing of provider facts; simpler, but the duplication stays.
- **A `disabled_reason` string** instead of `revoked`: rejected, there is one reason.
- **Secrets with several `project_id`s**, or `admin_secrets` beside `project_secrets`: covers shared secrets but leaves repositories and datasets duplicated.
