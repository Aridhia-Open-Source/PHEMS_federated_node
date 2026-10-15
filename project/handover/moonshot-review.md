> Model-generated review (a read-only sub-agent), run against `origin/dagster-develop-preview`. Line numbers and counts are unverified leads, not facts: check them before relying on them. The conclusions are folded into [ADR 0019](../decisions/0019-global-resources-and-shared-pull-requests.md).

# Moonshot review: ADR 0019 against origin/dagster-develop-preview

Paths are relative to the repo root on origin/dagster-develop-preview. Line numbers are from that branch.

## Verdict

The direction holds. The schema split is sound and removes some real pain: the `projects`/`datasets` FK cycle (`webserver/app/models/project.py:26-40`, baseline line ~345), the composite `(project_id, secret_id)` FKs, and the per-project copy of every PR.

"The API stays flat, Dagster is unchanged except ingest" is **not true as written**. Real problems, each traced to code:

1. **The flat `id` has to be the assignment id, and the ingest change needs the global id.** Every Dagster call is keyed on the flat repo `id`:
   - `GET/PATCH /trigger_repositories/<id>/pull_requests/<number>`, `.../task`, `get_pull_requests(repo_id)`, `get_results_repository_by_id`.
   - It is also the evaluate job tag, `pr_evaluate.py:174`.
   - The batch endpoint is the only call that should take the global repo id.
   - So the flat DTO needs at least one new field (global repo id), and the batch endpoint changes meaning. The ADR calls this "one sensor change"; it is a sensor change, an endpoint semantics change, and a DTO addition.
2. **Dagster DTOs do change.** `dagster/app/models/secret.py:24-25` requires `project_id: int` and `label: str`. The ADR's global `secrets` has neither. `dagster/app/models/dataset.py:28` requires `project_id`. `ResultsRepository` and `TriggerRepository` require `project_id` (`:24`).
   - Dagster can keep `project_id` on the repo and dataset DTOs, since the assignment supplies it.
   - The nested secret's `project_id` and `label` must become optional or be removed. Nothing in Dagster reads either (it uses `key`, `namespace` and `provider` only).
   - The ADR also drops `label`, but every API and the fncli address secrets by label (`secret_label` in trigger repo, results repo and dataset POST/PATCH; `fncli` `get_secrets`, `upsert_secret`). A global, unique `label` (or an equivalent name) must stay.
3. **Revocation and disable are invisible to Dagster, and in-flight work needs them visible.** The flat repo DTO has no `enabled` or `revoked` field today. Three Dagster paths break if inactive assignments are simply omitted from the lists:
   - `ResultsDelivery.get_results_repository(task.project_id)` does `(repository,) = response.json()` (`dagster/app/backend.py:189`). An empty list is an unpack `ValueError`, so a task already SUCCESS and awaiting delivery fails after a revoke.
   - `ResultsDelivery._find_pull_request` (`dagster/app/delivery/results.py:~172-178`) finds the task's trigger through `get_repositories()` filtered by project. A revoked or disabled trigger assignment makes it raise `LookupError`, and results cannot be delivered.
   - `pull_request_sync.py:276` calls `get_results_repository_by_id(result.results_repository_id)`. This must keep resolving revoked assignments, or the sync sensor raises on any result PUSHED or OPENED to a revoked repo.
   - So the contract has to be: lists and by-id endpoints return inactive rows with an `active` (or `enabled` and `revoked`) field, and the sensors filter. The ingest, evaluate and launcher sensors need that small filter change too.
4. **Dataset checks outside the task API are missed.**
   - `Task.validate` (`webserver/app/models/task.py:128`) and `Project.resolve_dataset` (`models/project.py:95-101`) are covered by the ADR.
   - `project.default_dataset` (`task.py:138`, `project.py:101`, `TriggerRepository.dataset` -> `dataset_id` in the DTO, `trigger_repository.py:296-300`) is not. Nothing ties `default_dataset_id` to an assignment, so a default can be unassigned or revoked and tasks would silently run on it. Make it a composite FK `(project_id, default_dataset_id)` -> `project_datasets(project_id, dataset_id)` and check `active` in `resolve_dataset`.
   - `task_launcher` calls `GET /datasets/<id>` (`launcher.py:216`), which is not project-aware. "Task launch uses only active assignments" needs either a project-aware dataset lookup or an `active` flag in the response, so that is a launcher edit.
5. **Dataset delete cascades into tasks across projects.** `task_specs.dataset_id` is `ON DELETE CASCADE` (`001_baseline.py:221-223`, `models/task_spec.py:17`), and `tasks.task_spec_id` is `ON DELETE CASCADE` onto `task_specs` (`001_baseline.py:~246`). Deleting a dataset deletes the tasks that ran on it. Today that is gated by `require_drained(project)` (`datasets_api.py:140`) and touches one project. For a global dataset, whose project do you drain?
   - Also change the cascade to RESTRICT or SET NULL.
   - Same question for PATCH (`datasets_api.py:164-166`) and global `secret` PATCH or DELETE.
   - A rule is needed: all assigned projects locked and drained, or an explicit exemption like the secret-rotation one.
6. **The batch ingest endpoint is not idempotent, so "dedupe storage only" does not work.** `post_pull_requests_batch` (`trigger_repositories_api.py:243-265`) turns any `IntegrityError` (uq_pr_repo_number) into a 400 for the whole batch. With a shared `pull_requests` table, the second project's sensor tick re-sends PRs already stored. It must become an upsert plus fan-out whichever way the open item on the sensor goes.
7. **Cursor semantics are inconsistent in the ADR.**
   - The ADR says "cursor is max `merged_at` of that assignment's triggers". But ingest polls once per global repo, so the poll cursor must be max `merged_at` of `pull_requests` (global). The assignment cursor is a different thing: where its fan-out starts.
   - `initial_cursor` earlier than stored history cannot be satisfied by polling the provider, because the global cursor is already ahead. It needs a backfill from `pull_requests` into new triggers when an assignment is created.
   - The same backfill is needed when an assignment is re-enabled or un-revoked. Fan-out only happens "when a pull request is stored" (ADR 3), so PRs merged while it was inactive never get a trigger.
   - The ADR must state both. `TriggerRepositoryDTO.pr_cursor` (`dtos/trigger_repository.py:19`) and `get_pull_request_cursor` (`trigger_repository.py:302-313`) can serve either meaning today. The flat DTO needs both a per-assignment and a global one.
8. **Loop check, project delete, DAR.**
   - `check_no_loop(project_id, uri)` (`helpers/repository_loop.py:378-398`) joins trigger and results repos by `(project_id, uri)`. It must move to the assignment tables (watch_dir and target_dir are per-project there). Cross-project loops, P1's results repo being P2's trigger repo, are newly possible because uri is now global. That is a policy decision, not a hypothetical.
   - `delete_project` (`projects_api.py:109-155`) deletes the project's secrets, datasets and repos, and deletes the stored K8s secret values. Under the global model it must only delete assignments, and must **not** call `SecretProvider.delete`.
   - `DAR.__init__` derives `project_id` from `dataset.project_id` (`models/extras/dar.py:67`) so a DAR cannot name another project's dataset. That is disconnected code (TODO(DAR)), but it will not import-fail and silently breaks; it needs the project passed in.
9. **ADR 0013 is already contradicted.** `webserver/migrations/versions/002_result_step_state_project_lock.py` exists on the preview branch (PR #548). Decide: fold 002 and the moonshot into the baseline (consistent with 0013) or freeze 001 and add 003. Do not mix.
10. **Secret keys.** `Secret.key` is `"<project_id>-<label>"` (`models/secret.py:62-81`, validated as a DNS subdomain by #543). Global keys need a new generation rule. Label uniqueness is `UNIQUE(project_id,label)` today; it becomes global unique.

Things the ADR gets right and are cheap:
- `Dataset.name` is already globally unique (`models/dataset.py:42`), so de-dup by name is a no-op for existing data.
- `tasks`' `dataset_id` (actually `task_specs.dataset_id`) and `projects.default_dataset_id` already point at `datasets.id`. No repoint is needed, only the assignment check.
- `Trigger.project_id` stays, so `Task.project_id`, `in_flight_task_ids` and `Task.trigger_id` unique all keep working.

## 1. Claim-by-claim check

### (a) Flat API and Dagster

What Dagster reads (`dagster/app/backend.py`):

| Call | Endpoint | Fields used |
|---|---|---|
| `get_projects` | `GET /projects` (paged) | `id`, `name`, `enabled`, `locked`, `default_dataset_id` |
| `get_repositories` | `GET /trigger_repositories[?project_enabled=true]` | `id`, `uri`, `provider`, `api_uri`, `secret{key,namespace,provider}`, `watch_dir`, `base_branch`, `project_id`, `dataset_id`, `initial_cursor`, `pr_cursor`, `pr_count` |
| `get_repository` / `patch_repository` | `/trigger_repositories/<id>` | same shape |
| `get_pull_requests` | `GET /trigger_repositories/<id>/pull_requests?state&page&per_page` | `trigger_repository_id`, `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`, `state`, `state_cause`, `task_id` |
| `create_pull_requests_batch` | `POST /trigger_repositories/<id>/pull_requests/batch` | body is the facts only (`dump_new`) |
| `patch_pull_request` | `PATCH .../<number>` | `state`, `state_cause` |
| `create_task_for_pull_request` | `POST .../<number>/task` | `spec_raw` |
| `get_tasks`, `get_task`, `patch_task` | `/tasks` | unchanged |
| `get_results_repository` | `GET /results_repositories?project_id=` | expects exactly one |
| `get_results_repository_by_id` | `/results_repositories/<id>` | |
| `create_result`, `patch_result`, `get_results_by_step` | `/results` | `results_repository_id` |
| `get_dataset` | `GET /datasets/<id>` | `id`, `project_id`, `secret`, `name`, `host`, `port`, schemas, `type`, `extra_connection_args`, `slug`, `url` |

Changes needed:
- **Fields to add:** the global repo id on the trigger-repo DTO; `active`/`enabled`/`revoked` on trigger repo, results repo and dataset DTOs; a way to get a project's datasets with activeness.
- **Fields that must keep their meaning:** `id` is the assignment id; `project_id` is the assignment's project; `pr_cursor`.
- **Fields that can go or become optional:** `secret.project_id`, `secret.label` (Dagster side only).
- **Endpoints:**
  - The batch endpoint takes the global id.
  - `POST /trigger_repositories` and `POST /results_repositories` split into global create plus assign. `dagster/app/backend.py` `create_repository`, `create_dataset` and `delete_*` (lines 234-307) are only used by tests and fncli; keep or move them.
  - `GET /results_repositories?project_id=` needs the "exactly one" decision on inactive.
- **Dagster code that changes:**
  - `models/secret.py`
  - `models/dataset.py`
  - `pr_ingest.py` (poll once per global repo; group the flat list by global id)
  - `pr_evaluate.py`, `launcher.py` and `delivery/results.py` (active filtering and the revoked-in-flight cases above)
  - `backend.py` (new fields, `create_*`)
- Sensors and models in the rest of `dagster/app/definitions/` do not change.

### (b) Datasets

Every place that depends on `dataset.project_id`, `project.datasets`, `default_dataset_id`, `tasks.dataset_id`:
- `models/dataset.py:30-31, 61-63, 76`: `project_id` column, `project` relationship, `__init__`.
- `models/dataset.py:87-97` (`Dataset.add`): first dataset into a project becomes the default. This moves to assignment creation.
- `models/project.py:26-40`: `default_dataset_id`, `datasets` relationship (`foreign_keys="Dataset.project_id"`), `default_dataset` `post_update`. The cycle workaround goes.
- `models/project.py:89-101` `resolve_dataset`: filter becomes a join through `project_datasets` with `active`.
- `models/task.py:121-138` (`Task.validate`, the API path) and `dtos/task.py:316` (`NewTaskDTO.from_spec`, used by both API and PR paths).
- `models/task_spec.py:17`: the cascade (problem 5).
- `models/trigger_repository.py:295-300`: `dataset` property reads `project.default_dataset`.
- `datasets_api.py`:
  - `:44-48` `?project_id=` filter (needs a join).
  - `:78` POST requires `project_id`.
  - `:140`, `:164-166` `require_drained(Project.get_by_id(ds.project_id))`.
  - `:165` PATCH allows moving `project_id`.
  - `:181` `_resolve_secret(... project_id)`.
- `dtos/dataset.py:14`, `DatasetDTO.project_id`; Dagster `Dataset.project_id`.
- `projects_api.py:131-134`: delete order.
- `models/extras/dar.py:67`.
- fncli: `backend.py:188-201` (`find_dataset(name, project_id)` compares `dataset.project_id`), `cmds/dataset.py:24,35,57`.
- `Dataset.get_all(project_id=...)` through `BaseModel._query` (`base_model.py:44`), used by `get_datasets`.
- `catalogue` and `dictionary` hang off `dataset_id` only, so they are unaffected.
- Keycloak `auth(check_dataset=...)` (`wrappers.py:52-54`) looks the dataset up by name or id, with no project. That is fine and unchanged.

The flat `DatasetDTO.project_id` has no single value for a global dataset. Options: omit it and let Dagster make it optional (Dagster never reads it), or return the caller's `?project_id=` context.

### (c) Secrets

Today:
- Creation: `secrets_api.py:127-167`. `Secret(project_id, label, ...)`, key `"<project_id>-<label>"`, the K8s store is written first, then the row.
- Reference: `GitRepositoryMixin.secret_id` plus composite FK `(project_id, secret_id)` -> `secrets(project_id, id)` on `trigger_repositories`, `results_repositories` and `datasets` (`models/secret.py:34-39`, `trigger_repository.py:264-267`, `results_repository.py:359-362`, `dataset.py:46-49`). Resolution is by label in the same project (`Secret.get_in_project`, used at `trigger_repositories_api.py:107,167`, `results_repositories_api.py:237,297`, `datasets_api.py:64,181`).
- Delete: `secrets_api.py:194-225` counts the three relationships and refuses while used (409), `require_drained(project)`, then deletes the row and the store value.
- PATCH (rotation) is exempt from the lock (`secrets_api.py:170-191`) and repos' `secret_label`-only patches are exempt (`trigger_repositories_api.py:145`, `results_repositories_api.py:280`).

What the global model changes:
- The whole `secrets_api.py` (225 lines) goes from `/projects/<id>/secrets` to `/secrets`.
- Drop both composite FKs and `UNIQUE(project_id,id)`.
- `Secret.get_in_project` becomes `get_by_label`.
- Delete checks the global resources' usage only.
- `project_id` is removed from `SecretDTO`.
- Rotation now affects every project that uses the credential (a deliberate effect of the design). Rotation stays exempt from the lock.
- The `K8sSecretProvider` and `SecretProvider` classes in `secrets_api.py:55-95` are unchanged.
- `projects_api.delete_project` must stop deleting secrets and their values.

### (d) Pull requests

Current structure:
- `Trigger` (`models/trigger.py`): `project_id`, `state`, `state_cause`, `spec_raw` setter.
- `PullRequestTrigger(Trigger)` (`models/pull_request_trigger.py:41-123`): `number`, `title`, `raised_by`, `merge_commit_sha`, `merged_at`, `spec_raw`, `trigger_repository_id` (FK CASCADE), unique `uq_pr_repo_number (trigger_repository_id, number)`.
- Cursor: `TriggerRepository.get_pull_request_cursor` = `max(PullRequestTrigger.merged_at)` for the repo, else `initial_cursor`. `validate_initial_cursor` refuses a change while triggers exist (`trigger_repository.py:278-293`).
- Ingest: `pr_ingest.py:50` polls per repo and posts the batch. The endpoint creates a `PullRequestTrigger` for the repo's own project.
- Task creation: `post_task` (`trigger_repositories_api.py:352-400`), idempotent on `pr.task`, rejects with `REJECTED` and `state_cause`. `NewTaskDTO.from_spec(spec, pr)` reads `trigger.project.resolve_dataset`, `trigger.title`, `trigger.requested_by`, `trigger.project_id`, `trigger.id`.

Fit of the ADR:
- `pull_requests` plus per-project `pull_request_triggers` fits the hierarchy: `Trigger.project_id` stays, `title`/`raised_by`/`requested_by` become properties via the new `pull_request` relationship, and `Task.trigger_id` stays unique per project.
- ADR errors and gaps are items 1, 6 and 7 above. In short: a global id for ingest, the batch endpoint as upsert plus fan-out, two cursors, and backfill on assignment create and re-enable.
- A pre-existing hazard the redesign should settle: `pull_request_triggers.trigger_repository_id ON DELETE CASCADE` deletes only the child row; the `triggers` parent row and its `tasks.trigger_id` (RESTRICT) survive. Deleting a repo leaves a polymorphic orphan. Choose the new delete semantics for `project_trigger_repositories` (probably RESTRICT while triggers exist) rather than copying the CASCADE.
- `pr_count` in the flat DTO (`len(obj.pull_request_triggers)`) and the healthcheck count (`projects_api.py:183`) stay per assignment.

### (e) Results

Current:
- `results_repositories` has `UNIQUE(project_id)` (`models/results_repository.py:357`, "one per project for now"). `Project.get_results_repository` is "the only place that assumes it" (`models/project.py:82-87`), plus `get_results_repository` in Dagster and healthcheck.
- `results (task_id, results_repository_id)` unique; FK RESTRICT to `results_repositories` (`models/result.py:24`).
- Delivery: `ResultsDelivery.__call__` fetches the project's repository then `create_result(task.id, repository.id)`. Sync reads by `result.results_repository_id`, "which may not be the project's current one".
- Lock: `require_drained` guards results repo POST/PATCH/DELETE (`results_repositories_api.py:212,236,281`). `Project.in_flight_task_ids` (`models/project.py:61-80`) counts PENDING/QUEUED/RUNNING, SUCCESS with no result, and PullRequestResult `IN_PROGRESS`.

With the ADR:
- `UNIQUE(project_id)` moves to `project_results_repositories`.
- `results.results_repository_id` repoints to the assignment id; unique `(task_id, results_repository_id)` still means one delivery per task.
- Revoking with in-flight work: item 3. `in_flight_task_ids` already counts exactly the tasks that need the assignment (SUCCESS without result, IN_PROGRESS delivery), so revoke vs lock is a policy gap: revoke is a system action and must not need the project locked, yet it breaks deliveries. Recommended minimum: keep returning the revoked row from by-id and list endpoints, and make delivery fail with a clear recorded error (it already records `error`, `FAILED` and re-launches by hand) instead of a `ValueError`; block revoke while `in_flight` or accept the failed-delivery outcome explicitly.
- The ADR does not say whether `project_results_repositories.enabled=false` or `revoked` also covers rows with in-flight results.
- `check_no_loop` moves to assignments (problem 8). `ResultsBackend` (`models/results_backend.py`) is unrelated and stays.

## 2. Code replaced or deleted

Rough counts are current lines in the file; "new" is estimated.

**Webserver models** (`webserver/app/models/`)
- `secret.py` (84): rewritten (~60, drops project FK, composite FKs, `get_in_project`).
- `trigger_repository.py` (105): rewritten into global model (~40) plus new `project_trigger_repository.py` (~90).
- `results_repository.py` (55): rewritten (~30) plus new `project_results_repository.py` (~50).
- `dataset.py` (231): edited (~35 lines, remove project, `add()` default logic, relationships); the rest (Keycloak, credentials, validate) untouched.
- `git_repository.py` (147): lightly edited (drop `project_id` column, secret doc); `get_token` / connection checks untouched.
- `project.py` (104): edited (~40: relationships, `resolve_dataset`, `get_results_repository`).
- `pull_request_trigger.py` (74): rewritten (~60), new `pull_request.py` (~40).
- `trigger.py` (85), `task.py` (268), `task_spec.py`, `result.py` (34), `extras/dar.py`: light edits (~5-30 lines each). `__init__.py` registry: +4 models.
- New `project_datasets` model (~35).
- Untouched: `api_request_trigger`, `result_state`, `pull_request_result*`, `results_backend`, `git_provider`, enums.

**Webserver APIs and helpers**
- `secrets_api.py` (225): rewritten (URL scheme and queries; ~150 changed).
- `trigger_repositories_api.py` (400): rewritten (~280 changed; the PR endpoints change internals only).
- `results_repositories_api.py` (170): rewritten (~120).
- `datasets_api.py` (272): edited (~60) plus assignment endpoints (new, ~100).
- `projects_api.py` (221): edited (~50: delete, healthcheck) plus assignment endpoints (shared with above).
- `tasks_api.py` (335), `results_api.py` (148): light (task validation, `results_repository` lookups).
- `helpers/repository_loop.py` (46): rewritten (~35). `helpers/project_lock.py` (18): extended to global resources (~25).
- New `datasets`, `trigger`, `results` assignment routes: ~250 lines in total.
- Untouched: `dar_api`, `admin_api`, `dagster_api`, `registries_api`, `users_api`, `whitelisted_images_api`, `main.py`, `keycloak`, `kubernetes*`.

**DTOs** (`webserver/app/dtos/`)
- `secret.py`, `trigger_repository.py`, `results_repository.py`: rewritten (~15-50 each).
- `dataset.py`, `project.py`: light.
- `task.py`: `NewTaskDTO.from_spec` light.

**Migration**
- `webserver/migrations/versions/001_baseline.py` (371): the `secrets`, `datasets`, `trigger_repositories`, `results_repositories`, `pull_request_triggers`, `results` blocks (~lines 45-135, 185-205, 255-275, 345) rewritten (~120 changed, +~80 new for the four new tables). Plus the `002` question.

**Webserver tests** (10,160 lines total)
- Rewritten: `test_secrets.py` (440), `test_trigger_repositories.py` (940), `test_results_repositories.py` (370), `test_dataset_secrets.py` (211).
- Heavily edited: `test_datasets.py` (969, ~18 fixture references), `test_projects.py` (500), `test_project_lock.py` (314), `conftest.py` (448; fixture builders), `test_whitelisted_images.py` (437, project fixtures).
- Light: `tasks/*`, `test_results.py`, `test_pagination.py`, `test_triggers.py`, `test_dtos.py`, `test_audits.py`.
- Roughly 2,500-3,000 of the lines rewritten or heavily edited.

**Dagster** (`dagster/app/`)
- Models: `secret.py`, `dataset.py` (optional fields), `trigger_repository.py` (new fields): light. `results_repository.py`, `pull_request_trigger.py`: light.
- `backend.py` (307): ~40 lines changed (`create_*` helpers, new fields).
- Sensors: `pr_ingest.py` (50): rewritten (~40). `pr_evaluate.py`, `launcher.py`, `delivery/results.py`: light edits for active filtering and revoked cases.
- Tests: `conftest.py`, `test_backend.py`, `test_models.py`, `test_pr_ingest_sensor.py`, `test_task_launcher.py`, `test_results_delivery.py`, `test_pr_evaluate_sensor.py`: ~300 lines touched.
- Untouched: `pipes.py`, `run_config.py`, `secrets.py`, run-status sensor, git clients, `delivery/git_push.py`.

**scripts/fncli** (3,898 lines)
- `dagster/backend.py` (382): ~40% (secret, dataset and repository helpers become global create plus assign).
- `cmds/secret.py` (187), `cmds/repository.py` (233), `cmds/dataset.py` (65): rewritten or heavily edited; `cmds/common.py` (146) edited (secret label naming now global); `cmds/verify.py`, `cmds/pr.py`, `cmds/project.py`: light.
- `dagster/models/*` (7 files, own copies): same edits as Dagster models.
- Tests `test_backend.py`, `test_dataset.py`, `test_config.py`, `test_pr.py`, `test_verify.py`: ~250 lines.
- `scripts/fncli/EXAMPLES.md`, `README.md`.

**Other**
- `webserver/app/static/openapi.json` (4,604): secrets, trigger and results repository, datasets paths and schemas, about 1,000+ lines.
- `dev.db/` seed scripts, `scripts/get_project.sh`, `scripts/init_repo.sh`: edited.
- Chart `k8s/federated-node`: untouched. It contains no schema or resource references; touched only if the ingest sensor interval changes.

**Docs and ADRs**
- Superseded or partly superseded: 0003 (project-scoped repositories), 0004 (secrets), 0001 (trigger hierarchy; `pull_request_triggers` facts move), 0006 (ingest per repo), 0007 and 0009 (one results repo, lock rules), 0013 (already broken by 002), 0015 (fncli flow), 0014 (authorization: controller permission).
- `docs/architecture/entities.md` (240) and `flows.md`: ER diagram and the composite-FK paragraph rewritten.

**Size estimate:** about 1,400 non-test webserver lines rewritten, +700-900 new (assignment models, routes, upsert and fan-out). Dagster is about 100-150 non-test lines. fncli is about 500 lines of code plus tests. Tests are about 3,000-3,500 lines across webserver, Dagster and fncli. openapi and docs add about 1,500 lines. Overall roughly 6-8k changed lines across ~90 files.

## 3. Overlap with the 15 PRs (all already in the preview branch)

The moonshot is cut from preview, so all 15 are in its base. The question is conflict and rebase cost if those PRs change or merge in a different order.

Substantial overlap (merge first, or expect rebase pain):
- **#548 project-lock/result step-state**: adds `project_lock.py`, `require_drained` in `secrets_api`, `datasets_api`, `trigger_repositories_api`, `results_repositories_api`, `projects_api`; `Project.in_flight_task_ids`; `002` migration; Dagster `backend.py`, `delivery/results.py`, `pr_ingest.py`, `pr_evaluate.py`, `pull_request_sync.py`. The moonshot's lock semantics for global resources build directly on it.
- **#547 task-spec-table**: `Task`/`TaskSpec`, `NewTaskDTO.from_spec`, `trigger.py`, `pull_request_trigger.py`, `dtos/trigger_repository.py`, Dagster `backend.py`, `evaluate_job.py`, `pr_parser.py`, `launcher.py`, `delivery/results.py`, fncli models. It rewrote the PR-to-task path the moonshot extends.
- **#543 k8s-name-validation**: `models/secret.py` and `secrets_api.py` key and label validation, which the moonshot rewrites.
- **#534 dataset-port-required**: `models/dataset.py`, `datasets_api.py`, `dtos/dataset.py`, baseline, many tests (`conftest.py` and others).
- **#531 json-body-object**: `trigger_repositories_api.py` (16 lines), `datasets_api.py`, `results_repositories_api.py`, `tasks_api.py`, `base_model.py`, Dagster and fncli `backend.py`, and +66 lines in `test_trigger_repositories.py`.
- **#535 uc1-seed-fncli**: `fncli/cmds/dataset.py`, `secret.py`, `common.py`, tests; deletes `dev.db` seeds (so the seed rewrite lives in fncli, which the moonshot then edits).

Minor overlap:
- **#526 beta-quick-wins**: Dagster `backend.py` `create_dataset` `project_id` param, which the moonshot reworks.
- **#533 fncli-follow-ups**: `cmds/pr.py`, `cmds/verify.py` (read `repository`/`project_id` fields).
- **#530 delivery-run-id**, **#529 delivery git timeout**: `delivery/results.py` and `git_push.py`. The moonshot touches only `_find_pull_request` in the same file.

Independent: **#528** (unused Dagster resources), **#532** (isolated test runs), **#544** (login form), **#545** (sensors API, `dagster_api.py`), **#546** (chart resources).

## 4. Recommended implementation order

Each stage leaves `webserver` tests runnable (the baseline is edited in place per ADR 0013, or 003 if you decide to freeze).

0. **Pin the flat contract** (below). No behavior change. Land first on `dagster-moonshot`.
1. **Secrets global.** `secrets` loses `project_id`; unique `label`; drop the composite FKs; `/secrets` API; update the three `secret_label` resolvers; `SecretDTO`. Dagster `Secret` model makes `project_id` and `label` optional. Fix `delete_project` not to delete secrets.
2. **Datasets global plus `project_datasets`.** `Dataset.project_id` removed, assignment model and endpoints, `resolve_dataset`, `Task.validate`, default dataset handled at assignment (composite FK), `task_specs` FK to RESTRICT, DAR fix, drained rule for global dataset edits. fncli dataset helpers.
3. **Results repositories global plus `project_results_repositories`.** `results.results_repository_id` repoints to the assignment; flat `GET /results_repositories` and by-id return assignment-joined rows including inactive ones with the activeness fields; healthcheck; loop check for results side.
4. **Trigger repositories global plus `project_trigger_repositories`**, with `pull_request_triggers` still holding the facts (FK to the assignment). Flat API with `id` = assignment id; loop check complete; `pr_cursor`, `pr_count`, `dataset_id` per assignment.
5. **`pull_requests` table, fan-out, upsert batch, backfill** on assignment create, enable and un-revoke. `PullRequestTriggerDTO` assembled from both tables.
6. **`enabled` and `revoked` behavior.** Sensors, launcher and delivery honor `active`; decide revoke vs lock and in-flight (items 3 and 9 above).
7. **Ingest sensor** polls once per global repo (global id field and global cursor).
8. fncli, `openapi.json`, `docs/architecture`, ADR updates (supersede 0003, 0004; amend 0001, 0006, 0007, 0009, 0013, 0015).

Stages 1-4 are mostly mechanical; the product questions (items 3, 5, 7 above) must be settled before stages 5-6.

### Minimum tests to add first (pin the flat shape)

Webserver, asserting exact key sets and types, not just status codes:
1. `GET /trigger_repositories` and `/<id>`: keys `id, uri, provider, api_uri, secret{id,project_id,label,description,provider,key,namespace,created_at,updated_at}, watch_dir, base_branch, project_id, dataset_id, initial_cursor, pr_cursor, pr_count`. Also pin that `pr_cursor` is `initial_cursor` with no PRs and max `merged_at` after, `?project_id=` and `?project_enabled=true` filters, `dataset_id` follows the project's default dataset.
2. PR endpoints keyed by `(repo_id, number)`: list (paged, `state` filter, `items/page/per_page/total`), get, patch state, `/task` (201 then 200 idempotent, 400 on bad spec with REJECTED recorded), `PullRequestTriggerDTO` key set; batch: 201, a duplicate number today returns 400 (pin it so the upsert change is deliberate).
3. `GET /results_repositories?project_id=` returns exactly one item with keys `id, uri, provider, api_uri, secret, target_dir, project_id, owned_by_federated_node`; `/results_repositories/<id>`; `results.results_repository_id` round trip through `/results` POST, GET and `step` filter.
4. `GET /datasets`, `/datasets/<id>` and `/datasets/<name>`: key set including `project_id` and nested secret; `GET /projects` item keys including `default_dataset_id`, `locked`, `enabled`; task DTO `spec.dataset_id`.
5. Task creation: API and PR paths both reject a dataset of another project, and fall back to the default dataset.
6. Healthcheck body shape.

Cross-service contract test: have the webserver tests dump these responses to a committed JSON fixture and have `dagster/app/tests/test_models.py` (and the fncli models) parse the same fixtures with the Dagster models. That catches the `secret.project_id`/`label` and `project_id` DTO breakage (problem 2) at test time instead of in a running sensor.
