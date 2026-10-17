# 0019. Global resources assigned to projects, with pull requests stored once per repository

- Status: Accepted (built). Stages 0-8 are done on the moonshot branches (local, not pushed).
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
| `project_secrets` | `id`, `project_id`, `secret_id`, `enabled`, `revoked` |

A project reaches a resource only through its own assignment row. The API returns secret references only, never values. `datasets.name` is already globally unique, so de-duplicating datasets by name is a no-op for existing data.

### 2. `enabled` and `revoked`

- `enabled`: a person turned the resource on or off for the project.
- `revoked`: the controller withdrew the project's access.

An assignment is **active** when `enabled` and not `revoked`. Revoking sets only `revoked`, never `enabled`, so a re-grant clears `revoked` and restores the previous state. Revoking affects only that resource; the project keeps running.

**Global `enabled`.** Resources can be switched on or off at both levels: each global resource (`trigger_repositories`, `results_repositories`, `datasets`, `secrets`) has its own `enabled` (not null, default true), set on the global `POST` and `PATCH`. A link is **active** only when its global resource is enabled, the link is `enabled` and the link is not `revoked`. A disabled global trigger repository is not polled and stores nothing: `GET /global/repositories/triggers?active_link=true` leaves it out and the batch ingest `POST` refuses it with a 400.

**Visibility contract.** The project assignment endpoints return inactive assignments too, with `enabled`, `revoked` and a computed `active`. Hiding them breaks in-flight work in Dagster: results delivery unpacks `(repository,) = ...` on the project's results repository (`dagster/app/backend.py:189`), `_find_pull_request` in `delivery/results.py` looks up the task's trigger repository through the list, and the results sync sensor resolves a result's repository by id (`pull_request_sync.py:276`). So the ingest, evaluate and launcher sensors filter on `active`, while delivery and results sync keep resolving inactive rows by id. A delivery that cannot proceed fails with a recorded error, not an unpack `ValueError`.

**Revoke takes effect immediately.** It is not blocked by in-flight work. Deliveries in flight for that assignment fail with a recorded error.

### 3. Pull requests stored once per repository

- New `pull_requests`: the provider's facts, shared by every project: `id`, `trigger_repository_id` (global), `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`, `base_branch` (the PR's target branch), `files_truncated`. Unique on `(trigger_repository_id, number)`. Replaces `uq_pr_repo_number`.
- New `pull_request_files(pull_request_id, path)`: the changed file paths, captured once at ingest together with `base_branch`. A table rather than a JSON array: paths are matched against `watch_dir` prefixes, a table can be indexed and filtered in SQL (backfill is then a plain query), and it needs no JSON operators across Postgres and the test database. The cost is one row per file, bounded by the provider cap below.
- **Provider cap.** GitHub pages the changed-files list and caps it at 3000. Ingest pages through all of it. A PR beyond the cap sets `files_truncated` and is treated as matching every path, because its watched files cannot be ruled out.
- `pull_request_triggers` stays per project and keeps the evaluation state (`state`, `state_cause` and `project_id` via `Trigger`, `spec_raw`, `task_id`). It gains `pull_request_id` and `project_trigger_repository_id` (replacing `trigger_repository_id`) and drops the duplicated facts; `title`, `raised_by` and `requested_by` become properties through `pull_request`. Unique on `(project_trigger_repository_id, pull_request_id)`. `Trigger.project_id`, `Task.project_id` and the unique `Task.trigger_id` are unchanged.
- **Fan-out:** when a pull request is stored, the backend creates a trigger for every active `project_trigger_repositories` row on that repository. It decides the match from stored data alone: the assignment's `base_branch` against `pull_requests.base_branch`, and its `watch_dir` against `pull_request_files.path` (or `files_truncated`). A matching trigger starts in its normal initial state (`UNKNOWN`). A non-matching link is skipped (logged) and gets no trigger. There is no `IGNORED` state. No provider call is made, so evaluate never calls the provider for a PR the project does not watch.
- **No re-processing.** `pull_requests` is unique on `(trigger_repository_id, number)` and written by upsert, the global cursor only moves forward, and triggers are unique on `(assignment, pull_request)`. Re-sending a PR changes nothing.
- **Config changes.** When an assignment's `watch_dir` or `base_branch` changes, matching runs forward from its cursor only. Older PRs are not replayed.
- **Upsert.** The batch ingest endpoint upserts the PRs and fans out, so a second project's tick re-sending PRs already stored changes nothing.
- **Two cursors.** The global poll cursor is the max `merged_at` of `pull_requests` for the repository. An assignment's cursor (`initial_cursor` with `initial_cursor_number`) is where its fan-out starts. It is set when the link is created, from the repository's latest stored pull request, or from the link's creation time when none is stored, so history is not replayed. No request sets it. A link that is enabled or un-revoked backfills what it missed. A global repository or provider that is switched back on moves every link's cursor to now (`initial_cursor` = now, `initial_cursor_number` = 0): the global poll cursor does not move while it is off, so a PR merged in the gap is ingested and stored once it is back on, but gets no trigger because the repository was disabled (e2e S9). The assignment DTO exposes the cursor it has reached (`pr_cursor`); the global repository DTO exposes the global one, which, with nothing stored yet, is the earliest creation of its active links.
- **Backfill.** Fan-out only runs when a pull request is stored, so it is not enough on its own. When an assignment is created, re-enabled or un-revoked, the backend backfills triggers from `pull_requests` and `pull_request_files` for the PRs it missed, with the same match rule. It is a database-only operation.
- **Delete semantics.** Today `pull_request_triggers.trigger_repository_id` is `ON DELETE CASCADE` and deletes only the child row, leaving the `triggers` parent and its `tasks.trigger_id` (RESTRICT) as an orphan. For `project_trigger_repositories` use RESTRICT while triggers exist.
- `pr_count` and the healthcheck count stay per assignment.

### 4. API and Dagster sensors

There is no flat compatibility API. The API exposes the real model, laid out as in section 11: global resources under `/global`, a project's links under `/projects/<id>`, both keyed by the global resource's id.

Pull requests:

- Facts on the global repository: `/global/repositories/triggers/<id>/pull_requests` (the batch ingest, upsert plus fan-out).
- A project's evaluation state under its link: `/projects/<id>/repositories/triggers/<repository id>/pull_requests/<number>`.

Dagster sensors use these directly:

- **Ingest** loops over global trigger repositories with an active link and polls each once, with the repository's own secret.
- **Evaluate and launch** loop over enabled, unlocked projects, their active links and triggers.
- **Delivery** uses the task's results link.
- The evaluate job tag carries the project id and the global repository id.

Dagster's `Secret` model needs only `key`, `namespace` and `provider`. Its repository and dataset models are split into a global model and a link model. `dagster/fncli` imports these models from `dagster/app`.

### 5. Results repository lookups

`GET /projects/<id>/repositories/results` returns the project's link, with its flags, when it is inactive, rather than an empty list.

### 6. Datasets

- `tasks` reach a dataset through `task_specs.dataset_id`, and `projects.default_dataset_id` points at `datasets.id`.
- "The dataset belongs to this project" (`Task.validate`; `Project.resolve_dataset`; `NewTaskDTO.from_spec`) means the project has an active `project_datasets` row for it.
- `default_dataset_id` is a composite FK `(project_id, default_dataset_id)` to `project_datasets(project_id, dataset_id)`, and `resolve_dataset` checks `active`. This removes the `projects`/`datasets` FK cycle and its `post_update` workaround.
- The first dataset linked to a project becomes its default.
- `task_specs.dataset_id` and `tasks.task_spec_id` are RESTRICT, so a dataset a task ran on cannot be deleted.
- Global datasets have no `project_id`. `GET /global/datasets` lists them and a project's are `GET /projects/<id>/datasets`. POST takes no `project_id` and `DatasetDTO` has none.
- Datasets are addressed by id only, never by name; `DatasetDTO.url` uses the id.
- Dataset-level authorisation is out of scope here: the `check_dataset` option of the auth decorator is gone, and a later auth ticket owns it.

### 7. Secrets

- Secrets are global and addressed by `label`, which is unique across the node, because every repository and dataset POST/PATCH and fncli address secrets by `secret_label`. `Secret.get_by_label` resolves it.
- `Secret.key` is `"fn-secret-<label>"`, fixed at creation, still a valid DNS subdomain (#543 validates it).
- There are no composite FKs on `project_id`. Delete checks the global resources' usage only.
- Rotating a secret affects every project using it, by design, and stays exempt from the project lock.
- `delete_project` deletes the project's links only. It does not delete secrets, datasets or repositories, and does not call `SecretProvider.delete`.

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

### 11. Resource URL layout

Datasets, secrets, trigger repositories and results repositories are all **resources**. Each exists globally and is linked to projects. Every URL is either global or under one project.

| Scope | Path | Methods |
|---|---|---|
| Global | `/global/datasets/:id`, `/global/secrets/:label`, `/global/repositories/triggers/:id`, `/global/repositories/results/:id` | `POST` on the collection creates; `GET`, `PATCH` and `DELETE` manage |
| Project | `/projects/:pid/datasets/:id`, `/projects/:pid/secrets/:label`, `/projects/:pid/repositories/triggers/:id`, `/projects/:pid/repositories/results/:id` | `GET` lists or reads the link; `PUT` links (201 first time, 200 after); `PATCH` changes the project's settings; `DELETE` unlinks |

- **One id.** Project paths use the global resource's id (a secret's label), never the link row's id. A project's view of a resource is addressed by `(project_id, resource id)`, so the link id leaves the API. The global API is where resources are found before linking them.
- **Projects never create resources.** `POST` exists only under `/global`. A resource only one project uses is a global resource linked to that one project.
- **Secrets follow the same rule.** A project can be linked to a secret (`project_secrets`, with `enabled` and `revoked`). The API returns references only, never values.
- **Results are project-scoped.** A result belongs to a task, so it lives under `/projects/:pid/results` and `/projects/:pid/results/:id` (`GET` lists or reads, `POST` creates the delivery, `PATCH` records its progress); a result whose task is in another project is a 404. An admin endpoint across projects may come later.
- **No cross-project lists.** `GET /project_trigger_repositories` goes. Ingest reads `GET /global/repositories/triggers` filtered to repositories with an active link of an enabled project; `PullRequestEvaluateSensor` loops over enabled, unlocked projects and reads each project's links (one extra list call per project per tick). `TaskLauncherSensor` already loops over projects and reads no trigger links.
- **`PUT` replaces.** Fields left out of a `PUT` body take their defaults; use `PATCH` to change one setting.
- **Sub-resources nest under their parent, in its scope.** A pull request's facts are under the global repository (`/global/repositories/triggers/:id/pull_requests`, including the batch ingest); a project's trigger for it is under the project's link (`/projects/:pid/repositories/triggers/:id/pull_requests/:number`).
- **`PUT` takes the project's own settings only.** `revoked` is the controller's, so only `PATCH` sets it (admin only) and a `PUT` leaves it alone. A trigger link is unique on `(project_id, trigger_repository_id)`, so a project watches one directory per repository.
- **Results carry the global results repository id.** `POST /projects/:pid/results` and the result DTO carry it; the row still points at the link.
- **Global `enabled`.** Each global resource carries `enabled` (settable on `POST` and `PATCH`, shown in the DTO) and a link is active only when the resource is enabled, the link is enabled and not revoked (section 2). The ingest filter and the batch ingest both honour it.
- **Ingest is only the global batch.** There is no single-PR project route. The ingest filter is `GET /global/repositories/triggers?active_link=true`.

- **Filter in the webserver.** Clients (Dagster, fncli) don't fetch lists and filter them in Python. Every filter they need is a query option on the list endpoint, e.g. `?active_link=true`.
- **Parked:** lock, drain and enabled guards on editing, deleting or unlinking resources (for example `DELETE /global/secrets/:label`) stay as built and are not revisited for now. Worst case a project keeps failing or is missing a secret.

### 12. Decisions settled

1. Revoke takes effect immediately; in-flight deliveries fail with a recorded error (section 2).
2. Editing or deleting a global dataset, repository or secret requires every assigned project locked and drained; secret rotation stays exempt (section 9).
3. Cross-project loops are forbidden (section 9).
4. `GET /projects/<id>/results_repositories` returns inactive assignments with their flags (section 5).
5. Global datasets have no `project_id` (section 6).
6. Migration: fold 002 and this change into the baseline (section 10).
7. Creating global resources and grants: admin role for now; revisit with the authorization rework (section 9).
8. `whitelisted_images`: not now (section 9).
9. URLs are `/global/...` or `/projects/:pid/...`, keyed by the global id; `POST` only under `/global`, `PUT` links (section 11).
10. Trigger states are `UNKNOWN`, `YIELDED` and `REJECTED`; `REJECTED` is final. Only an `UNKNOWN` trigger can get a task: `POST /projects/<pid>/repositories/triggers/<id>/pull_requests/<n>/task` returns 409 for a `REJECTED` trigger or an inactive link.
11. `GET /projects/<pid>/repositories/triggers?active=true` returns only active links. The evaluate sensor uses it.
12. `PATCH /tasks/<id>` returns 409 for a status change out of `SUCCESS`, `FAILED` or `CANCELED` (the same status is allowed; `/retry` still resets to `PENDING`).
13. `POST /results` returns 409 unless the task is `SUCCESS`; an existing result re-posts with 200. Through a revoked results link it creates the result as final, step `REVOKED` and state `FAILED`, and nothing is ever delivered for it (un-revoking the link does not deliver it; killing a task already running is post-beta). Through a link inactive for another reason (disabled by the project, or the global repository off) it returns 409 and is delivered once the link is active.
14. A repository or dataset that references a disabled secret is refused with 400 on create and patch.
15. Dataset `PATCH` returns 200 (?). `/tasks` clamps `page` and `per_page` below 1 to 1 (?).

## Consequences

- One credential, one set of pull requests and one provider poll per repository, however many projects use it.
- Each project keeps its own state, results and cursors, so projects stay independent.
- The controller's grant is the assignment row; revoking it stops only that connection.
- About 6–8k changed lines across roughly 90 files: ~1,400 non-test webserver lines rewritten and 700–900 new, tests ~3,000+, openapi and docs ~1,500. The chart is untouched. Without a flat layer the model change is larger: Dagster ~250–400 lines (split global and assignment models, new endpoints) and fncli ~600–800. The sensors get simpler, since nothing groups or translates ids.
- Creating global resources and grants uses the admin role until the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).
- Changed paths are fetched once per PR at ingest (paged), and no later per-project provider call is made for unwatched PRs.
- Heavy overlap with open PRs #548, #547, #543, #534, #531 and #535; light overlap with #526, #533, #529, #530; independent: #528, #532, #544, #545, #546.
- **Known gap (post-beta): the lock check and the change are two steps.** `require_drained` checks "locked and nothing in flight" and the change follows, while `post_task` (the evaluate sensor) checks only that the link is active, not that the project is unlocked. A task can be created between the check and the change. Worst case it runs against a setup that has just changed and fails or is not delivered (a revoked results link gives a `REVOKED` result); no data is lost and other projects are unaffected. Fix, small: `post_task` refuses a locked project with 409, and `require_drained` and `post_task` take a row lock on the project (`SELECT ... FOR UPDATE`) so they run one after the other.
- Supersedes or amends ADRs 0003, 0004, 0001, 0006, 0007, 0009, 0013 and 0015, and `docs/architecture/entities.md`.

## Implementation order

Each stage leaves the webserver tests runnable.

0. Contract tests (below): pin the unchanged endpoints; write the target shapes as strict `xfail` tests. No behaviour change.
1. Global secrets: drop `project_id`, unique `label`, drop the composite FKs, `/global/secrets`, the three `secret_label` resolvers, `SecretDTO`; Dagster `Secret` model; fix `delete_project`.
2. Global datasets plus `project_datasets`: assignment model and endpoints, `resolve_dataset`, `Task.validate`, the default-dataset composite FK, the cascade to RESTRICT, DAR; fncli dataset helpers.
3. Global results repositories plus `project_results_repositories`: repoint `results`; `/projects/<id>/results_repositories` includes inactive assignments; healthcheck; loop check for results.
4. Global trigger repositories plus `project_trigger_repositories`: assignment endpoints; complete the cross-project loop check; cursor, `pr_count`, `dataset_id` per assignment.
5. `pull_requests`, `pull_request_files`, fan-out that skips non-matching links, the upsert batch endpoint, and backfill on create, enable and un-revoke.
6. `enabled` and `revoked` behaviour in the sensors, launcher and delivery.
7. The Dagster sensors on the new endpoints: ingest per global repository, evaluate and launch per active assignment, delivery by the task's results assignment.
8. fncli, `openapi.json`, `docs/architecture`, ADR updates.

Stages 1–4 are mostly mechanical. The decisions in section 12 are settled.

## Contract tests to add first

Assert exact key sets and types, not just status codes. Stage 0 does two things.

**Pin what does not change shape:** the PR endpoints keyed by `(repo_id, number)` (list paged with `state` filter, get, patch state, `/task` 201 then 200 idempotent and 400 on a bad spec with `REJECTED` recorded); the `/results` round trip including the `step` filter; `GET /global/datasets/<id>`; `GET /projects` item keys including `default_dataset_id`, `locked`, `enabled`; the task DTO `spec.dataset_id`; the healthcheck body shape; task creation through the API and the PR path both rejecting a dataset of another project and falling back to the default dataset. Batch ingest: 201, and pin that a duplicate number returns 400 today so the upsert change is deliberate.

**Write the target shapes for changing endpoints as tests marked `xfail(strict=True)`:** global `GET /global/repositories/triggers` (`id` is the resource id), `GET /projects/<id>/repositories/triggers` and the results repository and dataset equivalents with the nested global resource and assignment fields, `/global/secrets`, PR ingest on the global repository, and fan-out that skips non-matching links. Each stage removes the marker from the tests it makes pass. A strict `xfail` that unexpectedly passes fails the run, so the flip cannot be forgotten.

Plus a cross-service check: the webserver tests dump these responses to a committed JSON fixture and the Dagster and fncli model tests parse the same fixtures. That catches the `Secret.project_id`/`label` breakage at test time.

## Alternatives considered

- **Keep everything project-scoped** (today): isolated, but repeated registration, polling, credentials and stored pull requests.
- **Pull requests per assignment only:** no sharing of provider facts; simpler, but the duplication stays.
- **A `disabled_reason` string** instead of `revoked`: rejected, there is one reason.
- **Secrets with several `project_id`s**, or `admin_secrets` beside `project_secrets`: covers shared secrets but leaves repositories and datasets duplicated.
