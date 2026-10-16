# Moonshot build plan for ADR 0019

Build plan for [ADR 0019](../decisions/0019-global-resources-and-shared-pull-requests.md) on `dagster-moonshot`. Docs only; nothing here is built.

Assumes the ADR is being updated in parallel with these decisions (the plan is written against them, not against the text on the branch today). If the merged ADR disagrees with a path or shape below, the ADR wins and the stage agent says so in its report.

- No flat compatibility API. Global resources live at `/trigger_repositories`, `/results_repositories`, `/datasets`, `/secrets` (id = the resource id). Per-project assignments live at `/projects/<id>/trigger_repositories`, `/projects/<id>/results_repositories`, `/projects/<id>/datasets` with the global resource nested. Provider facts about pull requests live at `/trigger_repositories/<id>/pull_requests`. Per-project triggers are addressed by assignment (working name: `/projects/<pid>/trigger_repositories/<assignment_id>/pull_requests/<number>[/task]`).
- Dagster sensors use these endpoints directly. Ingest polls each global repository once. Evaluate and launch loop over active assignments. Delivery uses the task's results assignment.
- `pull_requests` stores `base_branch` and the changed file paths at ingest. Fan-out matches from stored data. `IGNORED` is kept: fan-out creates a trigger per active assignment, `IGNORED` when nothing matches.
- Decisions: revoke is immediate (deliveries fail with a recorded error). Global edits need every assigned project drained (secret rotation exempt). Cross-project loops are forbidden. Inactive assignments are returned with flags. Global datasets have no `project_id`. Migrations are folded into the baseline. The admin creates global resources. `whitelisted_images` is not touched.

## 0. How to read this

- Stages 0 to 8 are sequential. They all edit the same tables, `001_baseline.py`, `conftest.py` and the Dagster/fncli models, so parallel stages would conflict. One subagent per stage.
- Usage is the bottleneck (one day, Claude Pro). **Window 1: stages 0 to 4. Window 2: stages 5 to 8.** Checkpoint A sits between them.
- Sizes are relative usage, not lines: S (under ~1 file-batch of work), M, L, XL.
- Line references below were checked against `origin/dagster-moonshot` (a11402ab). Two in the review are wrong and corrected here: the results-repository lookup in the sync sensor is `dagster/app/definitions/sensors/task/pull_request_sync.py:49` (not `:276`), and the launcher's dataset fetch is `dagster/app/definitions/sensors/task/launcher.py:35` (`backend.py:268` is the client method; `launcher.py:216` does not exist). Verified as stated: `backend.py:189`, `delivery/results.py:174-182`, `trigger_repositories_api.py:243-265`, `models/task.py:128`, `models/project.py:95-101`, `models/extras/dar.py:67`, `helpers/repository_loop.py` `check_no_loop`.

## 1. Cross-cutting design choices

**Migration.** Fold into the baseline (ADR 0013). Stage 1 folds `002_result_step_state_project_lock.py` into `001_baseline.py` and deletes 002; every later stage edits 001 in place. There is no data migration: existing databases are wiped and reseeded (the ADR's "split" migration is dropped; it only matters if a populated DB must survive, and none must before beta). The agent in stage 1 confirms with a grep that no environment file or chart job references revision `002_...`.

**Branching and PRs: stack.** Each stage branches off the previous stage's branch and its PR targets that branch (`moonshot/s0-contracts` targets `dagster-moonshot`; `moonshot/s1-secrets` targets `moonshot/s0-contracts`; and so on). Reasons: stages edit the same files, so a flat PR per stage off `dagster-moonshot` would have to be rebased after every merge, which burns usage; stacked PRs keep each diff to one stage and the base always green. Merge bottom-up, retargeting the next PR to `dagster-moonshot` after each merge. If the day stops at stage 4, merge 0 to 4 and leave the rest open.

**Worktrees.** `git fetch origin <prev-branch> && git worktree add -b moonshot/sN-name ../fn-worktrees/moonshot/sN-name origin/<prev-branch>` (S0 from `origin/dagster-moonshot`). The previous stage must be pushed first.

**Contract fixtures.** The webserver Docker build context is `webserver/`, Dagster's is `dagster/`, so a shared top-level directory is not visible inside containers. Layout:
- Source of truth: `webserver/tests/contract_fixtures/*.json`, written by the webserver contract tests. A test compares the live response with the committed file and fails on drift; `UPDATE_CONTRACT_FIXTURES=1` rewrites them. Placeholder values (ids, timestamps) are normalised so the files are stable.
- Copies: `dagster/app/tests/contract_fixtures/` and `scripts/fncli/tests/contract_fixtures/`, written by `scripts/sync_contract_fixtures.sh` (new, stage 0; plain `cp`). Every stage that changes a response runs the webserver test with `UPDATE_CONTRACT_FIXTURES=1`, then the script, then commits all three. A Dagster/fncli model test fails if a fixture does not parse.

**Contract test mechanics (stage 0).** Two kinds:
1. Pins of endpoints that do not change (PR state patch, `/task` idempotency, `/results` round trip, `/projects`, healthcheck, task DTO, tasks API dataset rejection and default fallback): plain tests, stay forever.
2. Endpoints that change: the target shape is written now as `@pytest.mark.xfail(strict=True, reason="stage N")`. The stage that builds it deletes the marker (strict xfail turns an unexpected pass into a failure, so a stage cannot forget to flip it). The old-shape tests for the same endpoint are deleted in that stage, together with the old code.

**Admin-only creation.** Global resource POST/PATCH/DELETE and assignment revoke use the existing admin check (the decorator `admin_api.py` uses; the agent finds it, copies it, adds no new permission model). Assigning to a project and enabling or disabling stays as today's project permission. Reads stay as today.

**Dagster and fncli stay green every stage.** Each stage that changes a response also updates, in the same commit, the Dagster model/backend/sensor that reads it and the fncli model copy. Dagster tests run in Docker; fncli tests run in a venv.

## 2. Test commands (used by every stage)

Foreground, sized timeout (~2 min per file, max 600000 ms per call; if a stage's list needs more, split into sequential calls). One pytest argument, quoted as one string:

```
cd <worktree>/webserver && ./run_tests.sh ci "tests/test_a.py tests/test_b.py"
```

Dagster (build once per stage, then the files):

```
cd <worktree> && docker build dagster -f dagster/build/test.Dockerfile -t dagster_test && docker run --rm dagster_test pytest -v app/tests/test_x.py app/tests/test_y.py
```

fncli:

```
cd <worktree>/scripts/fncli && python -m pytest -v tests/test_x.py tests/test_y.py
```

If the fncli venv is missing, the agent stops and reports rather than installing things. Never run the whole suite, never poll logs, never watch CI. On a failure: stop, report which test and the assertion, do not retry more than the single failing test once.

## 3. Dependency and parallelism

```
0 -> 1 -> 2 -> 3 -> 4 -> [Checkpoint A] -> 5 -> 6 -> 7 -> 8a -> 8b
```

- Strictly sequential for code: every stage edits `001_baseline.py`, `webserver/tests/conftest.py`, `webserver/app/models/__init__.py` and the model copies.
- Parallel without conflict: only docs. 8b (docs, openapi, ADR text) can start after 7 is pushed and runs concurrently with nothing else. The Gitea mirror (ADR 0020) must not start. A Haiku agent can draft `openapi.json` edits per stage in parallel with the next stage only if told to touch `openapi.json` and nothing else; not recommended, as it makes every stage's merge touch a 4,600-line JSON file. Keep it in 8b.
- Dependencies on decisions: all eight ADR decisions are already made (see top), so nothing blocks stage 5 or 6.

## 4. Stage summary

| Stage | Model | Size | Window |
|---|---|---|---|
| 0 Contract tests | Sonnet | M | 1 |
| 1 Global secrets | Sonnet | M | 1 |
| 2 Global datasets, `project_datasets` | Sonnet | L | 1 |
| 3 Global results repositories | Sonnet | M | 1 |
| 4 Global trigger repositories | Sonnet | L | 1 |
| 5 `pull_requests`, fan-out, upsert, backfill, cursors | **Opus** | XL | 2 |
| 6 `enabled`/`revoked` in sensors, launcher, delivery | Sonnet | M | 2 |
| 7 Ingest sensor once per global repository | Sonnet | S | 2 |
| 8a fncli | Sonnet | M | 2 |
| 8b openapi, docs, ADR updates | Haiku | M | 2 |

Opus is used only for stage 5: shared storage with per-project fan-out, backfill on four triggers (create, enable, un-revoke, earlier `initial_cursor`) and two cursor meanings is the one place where a plausible-looking implementation silently loses or duplicates triggers. Everything else is rewriting known code to a known shape. Haiku is used for 8b only; 8a edits CLI behaviour and tests, which needs Sonnet. If window 2 is short on usage, run stage 5 on Sonnet with the invariants list in its brief and the exactly-once test, and accept a rework risk.

---

## Stage 0. Contract tests

**Goal.** Pin what must not change, write the target shapes as strict xfails, add JSON fixtures that Dagster and fncli parse. No behaviour change.

**Files.**
- New `webserver/tests/contract/__init__.py`, `contract/helpers.py` (normalise and compare/write fixtures), `contract/test_pins.py` (unchanged endpoints), `contract/test_targets.py` (strict xfails).
- New `webserver/tests/contract_fixtures/*.json`.
- New `dagster/app/tests/test_contract_models.py` and `scripts/fncli/tests/test_contract_models.py`, each parsing every fixture with that package's own models.
- New `scripts/sync_contract_fixtures.sh`.
- `webserver/tests/conftest.py`: only if a fixture builder is missing; no edits to existing ones.

**Schema, endpoints, sensors.** None.

**Tests.**
Pins (pass now, from the ADR's list, with ids/timestamps normalised): PR state patch, `/task` (201 then 200 idempotent, 400 on a bad spec with `REJECTED` and `state_cause` recorded), PR list paging and `state` filter, `GET /results_repositories?project_id=` (exactly one item) and `/results` POST/GET with the `step` filter, `GET /projects` item keys including `default_dataset_id`, `locked`, `enabled`, the task DTO `spec.dataset_id`, API and PR path both rejecting another project's dataset and falling back to the default, the healthcheck body. Pin that a duplicate PR number in the current batch endpoint returns 400 (deleted in stage 5).
Strict xfails, each naming its stage: `/secrets` (stage 1), `/datasets` and `/projects/<id>/datasets` (2), `/results_repositories` and `/projects/<id>/results_repositories` (3), `/trigger_repositories` and `/projects/<id>/trigger_repositories` with `trigger_repository` nested, `pr_cursor`, `pr_count`, `active`, `enabled`, `revoked` (4), `/trigger_repositories/<id>/pull_requests` with `base_branch`, `changed_files` and the upsert batch (5), revoked assignment still returned with flags (6).
Hand-write the target fixtures for the xfail endpoints under `contract_fixtures/target/`; the Dagster/fncli target-model tests are also strict xfail and flip with the stage that updates the models.

Commands:
```
cd webserver && ./run_tests.sh ci "tests/contract/test_pins.py tests/contract/test_targets.py"
docker run --rm dagster_test pytest -v app/tests/test_contract_models.py      # after the build line
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py
```
Timeout: 240000 for the webserver call.

**Model.** Sonnet. It has to read the current DTOs precisely and write exact key-set assertions; Haiku would pin the wrong shapes and the whole plan rests on these.
**Size.** M (about 500 to 700 new test lines, no source edits).
**Risks.** Pinning a shape the ADR is about to change, so the old-shape tests must carry a comment naming the stage that deletes them. Normalisation hiding real drift (compare key sets and types strictly, normalise only values). Webserver tests need Docker and Postgres: if `run_tests.sh` cannot start, stop and report (the handover says Docker Hub rate-limits; images work from `mirror.gcr.io`).
**Done.** Pins green; xfails report `xfailed` not `xpassed`; the three fixture copies are identical; one commit; PR into `dagster-moonshot`.

---

## Stage 1. Global secrets

**Goal.** Secrets belong to no project. `/secrets` replaces `/projects/<id>/secrets`.

**Files.**
- `webserver/app/models/secret.py`: drop `project_id`, `UNIQUE(project_id,id)` and `UNIQUE(project_id,label)`; `UNIQUE(label)`; `get_in_project` becomes `get_by_label`; new key rule (no project prefix, still a DNS subdomain per #543; suggested `fn-secret-<label>`, the agent checks `helpers/kubernetes_names.py`).
- `webserver/app/models/git_repository.py` (`GitRepositoryMixin.secret_id`) and `models/trigger_repository.py`, `results_repository.py`, `dataset.py`: drop the composite FK `(project_id, secret_id)`, plain `secret_id` FK to `secrets.id`.
- `webserver/app/secrets_api.py`: routes to `/secrets`, `/secrets/<id>`; create, patch (rotation exempt from the lock), delete (409 while any repository or dataset uses it; no drain check); admin-only for create and delete.
- `webserver/app/trigger_repositories_api.py:107,167`, `results_repositories_api.py:237,297`, `datasets_api.py:64,181`: the three `secret_label` resolvers use `get_by_label`.
- `webserver/app/projects_api.py` `delete_project` (~109-155): stop deleting secrets and stop calling `SecretProvider.delete`.
- `webserver/app/dtos/secret.py`: remove `project_id`.
- `webserver/migrations/versions/001_baseline.py`: fold 002 in, delete 002, edit the `secrets` block and the FKs.
- Dagster and fncli `models/secret.py`: remove `project_id` and `label` (Dagster reads only `key`, `namespace`, `provider`; fncli reads `label`, keep it there as optional).
- Tests: `test_secrets.py` (rewrite for `/secrets`), `test_dataset_secrets.py`, `test_projects.py` (delete cases), `conftest.py` secret fixtures, flip the `/secrets` xfails, refresh fixtures.

**Schema.** `secrets(id, key, namespace, provider, label UNIQUE, description)`. Composite FKs and `UNIQUE(project_id,id)` gone.
**Endpoints.** `/secrets` replaces `/projects/<id>/secrets`. Existing nested `secret` objects on repository/dataset responses lose `project_id` for now.
**Sensors.** None; Dagster `Secret` model only.

**Tests and commands.**
```
cd webserver && ./run_tests.sh ci "tests/test_secrets.py tests/test_dataset_secrets.py tests/test_projects.py tests/contract/test_pins.py tests/contract/test_targets.py"
docker run --rm dagster_test pytest -v app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_secrets.py
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py tests/test_backend.py
```
Timeout: 600000 (5 files). `test_trigger_repositories.py`, `test_results_repositories.py` and `test_datasets.py` also build secrets in fixtures: run them once at the end in a second call (`"tests/test_trigger_repositories.py tests/test_results_repositories.py tests/test_datasets.py"`, 360000) because conftest changed.

**Model.** Sonnet: mechanical but the K8s name rule and delete ordering need judgment.
**Size.** M (about 700 changed lines, mostly tests).
**Risks.** The conftest secret fixture feeds almost every test, so one wrong edit fails many; fix it first. `delete_project` regressions (it must leave secrets and values). Key rule collisions across providers. #543 validation tests.
**Done.** Listed tests green; `/secrets` xfail flipped; grep `project_id` in secret code is empty; 002 gone, baseline has `locked` and `step`; one commit, stacked PR.

---

## Stage 2. Global datasets and `project_datasets`

**Goal.** Datasets global; assignment per project; default dataset tied to an assignment.

**Files.**
- `webserver/app/models/dataset.py`: drop `project_id`, `project` relationship, project part of `__init__`; `Dataset.add` no longer sets a default.
- New `webserver/app/models/project_dataset.py` (`project_datasets`); register in `models/__init__.py`.
- `webserver/app/models/project.py:26-40,89-101`: `datasets` relationship via assignments; `default_dataset_id` becomes a composite FK `(project_id, default_dataset_id)` to `project_datasets(project_id, dataset_id)`; remove the `post_update` cycle workaround; `resolve_dataset` joins `project_datasets` and requires active.
- `webserver/app/models/task.py:121-138` (`Task.validate`) and `dtos/task.py` `NewTaskDTO.from_spec`: "this project has an active `project_datasets` row".
- `webserver/app/models/task_spec.py:17` and baseline `task_specs.dataset_id` and `tasks.task_spec_id` (`001_baseline.py` around lines 221-247): `ON DELETE CASCADE` to `RESTRICT`.
- `webserver/app/models/trigger_repository.py` `dataset` property (stays reading `project.default_dataset` until stage 4).
- `webserver/app/models/extras/dar.py:67`: take `project_id` as a parameter; `dar_api.py` passes it.
- `webserver/app/datasets_api.py`: global CRUD at `/datasets` (admin-only create/patch/delete; no `project_id` in POST or PATCH; `?project_id=` filter removed); delete and PATCH need every assigned project drained (new helper `require_all_drained(projects)` in `helpers/project_lock.py`); assignment endpoints `/projects/<id>/datasets` (list with inactive rows and flags, POST assign, GET/PATCH/DELETE by assignment) in `projects_api.py` or `datasets_api.py`; first assignment in a project becomes its default.
- `webserver/app/dtos/dataset.py`: global DTO without `project_id`; new assignment DTO `{id, project_id, dataset, enabled, revoked, active}`.
- `webserver/app/projects_api.py` `delete_project`: delete only that project's dataset assignments (order changes).
- Dagster: `models/dataset.py` (remove `project_id`), new `ProjectDataset` model, `backend.py` (`get_dataset` stays by global id; add `get_project_dataset(project_id, dataset_id)`; `create_dataset` helpers), `definitions/sensors/task/launcher.py:35` uses the project dataset lookup and skips/fails when inactive (the failure path itself is finished in stage 6, here it just refuses). fncli: `dagster/models/dataset.py`, `dagster/backend.py:188-201` `find_dataset`, `cmds/dataset.py`.
- Baseline `datasets`, new `project_datasets`, `projects` FK.

**Schema.** `datasets(id, name UNIQUE, host, port, type, read_schema, write_schema, extra_connection_args, secret_id)`; `project_datasets(id, project_id, dataset_id, enabled, revoked, UNIQUE(project_id,dataset_id))`; `projects` composite default FK; RESTRICT on the task cascades.
**Endpoints.** As above.
**Sensors.** Launcher dataset lookup only.

**Tests and commands.** Rewrite or heavily edit `test_datasets.py`, `test_projects.py`, `test_project_lock.py`, `tasks/test_tasks.py`, `tasks/test_task_from_spec.py`, `conftest.py`; flip the `/datasets` and `/projects/<id>/datasets` xfails; add tests for: default composite FK rejects an unassigned default, revoked default refused by `resolve_dataset`, dataset delete blocked while any assigned project is not drained, dataset delete no longer deletes tasks.
```
cd webserver && ./run_tests.sh ci "tests/test_datasets.py tests/test_dataset_secrets.py tests/test_projects.py tests/test_project_lock.py tests/tasks/test_tasks.py tests/tasks/test_task_from_spec.py tests/contract/test_pins.py tests/contract/test_targets.py"
```
Timeout 600000. Then split: `"tests/test_trigger_repositories.py tests/test_results_repositories.py tests/test_results.py tests/test_dtos.py"` (timeout 480000) because fixtures changed.
```
docker run --rm dagster_test pytest -v app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_task_launcher.py app/tests/test_backend.py
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py tests/test_dataset.py tests/test_backend.py
```

**Model.** Sonnet. The hardest part (composite FK removing the cycle) is a known SQLAlchemy pattern, not new reasoning.
**Size.** L (about 1,200 changed lines).
**Risks.** `datasets.name` lowercasing and `get_dataset_by_name_or_id` used by Keycloak `auth(check_dataset=...)` (`helpers/wrappers.py`), which must keep working unchanged. Composite FK creation order in the baseline. `test_datasets.py` is 969 lines with many project fixtures; budget most of the usage here. `Dataset.get_all(project_id=...)` via `BaseModel._query` must stop being used with `project_id`.
**Done.** Tests above green; `grep -rn "dataset.project_id\|Dataset.project_id" webserver dagster scripts/fncli` returns nothing outside tests that assert absence; cascade is RESTRICT; one commit.

---

## Stage 3. Global results repositories and `project_results_repositories`

**Goal.** Results repositories global; one assignment per project; `results` tracks the assignment.

**Files.**
- `webserver/app/models/results_repository.py`: global (`uri`, `provider`, `api_uri`, `secret_id`; no `project_id`, `target_dir`, `owned_by_federated_node`).
- New `webserver/app/models/project_results_repository.py` (`project_id` UNIQUE, `results_repository_id`, `target_dir`, `owned_by_federated_node`, `enabled`, `revoked`); `models/__init__.py`.
- `webserver/app/models/result.py:24`: `results_repository_id` FK to `project_results_repositories.id` (RESTRICT); `(task_id, results_repository_id)` stays unique.
- `webserver/app/models/project.py:82-87` `get_results_repository` returns the assignment (including inactive).
- `webserver/app/results_repositories_api.py`: global CRUD at `/results_repositories` (admin-only; edit/delete requires all assigned projects drained; secret-label-only patch exempt); assignment routes `/projects/<id>/results_repositories` (list returns the inactive row with flags, so "exactly one" holds; POST, GET, PATCH, DELETE by assignment id; `target_dir` and flags live here).
- `webserver/app/results_api.py`: `results_repository_id` is an assignment id; `ResultDTO` gains `project_id` (so the sync sensor can resolve without an extra task fetch).
- `webserver/app/helpers/repository_loop.py`: `check_no_loop` moves to assignments for the results side, using the new tables; the trigger side is completed in stage 4. Cross-project loops forbidden here for the results side (a results assignment is refused if another project's trigger assignment on the same `uri` overlaps its `target_dir`; the symmetric check lands in stage 4).
- `webserver/app/projects_api.py`: healthcheck reads the assignment; `delete_project` deletes the assignment only.
- `webserver/app/dtos/results_repository.py`: global DTO and assignment DTO.
- Dagster: `models/results_repository.py` (global plus `ProjectResultsRepository` with nested repository), `backend.py:184-198` (`get_results_repository(project_id)` hits `/projects/<id>/results_repositories` and `(assignment,) = ...`; by-id resolves an assignment by `(project_id, id)`), `delivery/results.py:57`, `definitions/sensors/task/pull_request_sync.py:49` (uses `result.project_id`). fncli: `dagster/models/results_repository.py`, `dagster/backend.py` repository helpers.
- Baseline `results_repositories`, new `project_results_repositories`, `results`.

**Schema, endpoints.** As above.
**Sensors.** Delivery and sync resolve through assignments; no active filtering yet (stage 6).

**Tests and commands.** Rewrite `test_results_repositories.py`; edit `test_results.py`, `test_project_lock.py`, `test_projects.py`, `conftest.py`; flip the `/results_repositories` xfails; new tests: loop check against assignments, global edit blocked until all assigned projects drained, `results` rows FK to the assignment.
```
cd webserver && ./run_tests.sh ci "tests/test_results_repositories.py tests/test_results.py tests/test_project_lock.py tests/test_projects.py tests/contract/test_pins.py tests/contract/test_targets.py"
```
Timeout 600000.
```
docker run --rm dagster_test pytest -v app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_backend.py app/tests/test_results_delivery.py app/tests/test_results_pull_request_sync.py
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py tests/test_backend.py
```

**Model.** Sonnet.
**Size.** M (about 800 changed lines).
**Risks.** `results.results_repository_id` meaning flips from repository to assignment: the pre-existing pins and the Dagster delivery tests must be updated together. Loop-check semantics. The healthcheck body must keep its keys (pinned).
**Done.** Tests green; results xfail flipped; `GET /projects/<id>/results_repositories` returns the one row, active or not; one commit.

---

## Stage 4. Global trigger repositories and `project_trigger_repositories`

**Goal.** Trigger repositories global; assignment per project; per-project PRs addressed by assignment. Pull requests are still stored per assignment (facts included) in this stage: sharing arrives in stage 5.

**Files.**
- `webserver/app/models/trigger_repository.py`: global (`uri`, `provider`, `api_uri`, `secret_id`).
- New `webserver/app/models/project_trigger_repository.py` (`project_id`, `trigger_repository_id`, `watch_dir`, `base_branch`, `initial_cursor`, `enabled`, `revoked`; unique `(project_id, trigger_repository_id, watch_dir)` unless the ADR says otherwise); relationships `pull_request_triggers`; cursor logic (`get_pull_request_cursor`, `validate_initial_cursor`) moves here; `dataset` property reads the project's default dataset.
- `webserver/app/models/pull_request_trigger.py`: FK `trigger_repository_id` becomes `project_trigger_repository_id` with `ON DELETE RESTRICT` (replaces the CASCADE that orphaned the `triggers` parent); `uq_pr_repo_number` on `(project_trigger_repository_id, number)`.
- `webserver/app/trigger_repositories_api.py` (400 lines): global CRUD at `/trigger_repositories` (admin-only; edit/delete needs all assigned projects drained; secret-label-only patch exempt); assignment routes `/projects/<id>/trigger_repositories` (list with inactive rows and flags; POST assign; GET/PATCH/DELETE by assignment id; `pr_cursor`, `pr_count`, `dataset_id` per assignment); per-project PR routes under `/projects/<pid>/trigger_repositories/<assignment_id>/pull_requests[...]`, including `/task` (internals unchanged, keyed on assignment), and the existing batch endpoint moved there.
- `webserver/app/helpers/repository_loop.py`: complete `check_no_loop` over both assignment tables, forbidding cross-project loops (reject any trigger assignment whose `uri` and `watch_dir` overlap any project's results `target_dir`, and vice versa).
- `webserver/app/dtos/trigger_repository.py`: global DTO, assignment DTO (`id`, `project_id`, nested `trigger_repository`, `watch_dir`, `base_branch`, `initial_cursor`, `pr_cursor`, `pr_count`, `dataset_id`, `enabled`, `revoked`, `active`), `PullRequestTriggerDTO` keyed by `project_trigger_repository_id`.
- `webserver/app/projects_api.py`: healthcheck count per assignment; `delete_project` deletes assignments (after triggers are gone; RESTRICT means a project with triggers cannot be deleted until its triggers and tasks are, which matches today's drained requirement; the agent checks the current delete order).
- Dagster: `models/trigger_repository.py` (assignment with nested repository, `repo_path` derived from the nested `uri`), `models/pull_request_trigger.py`, `backend.py` (`get_repositories` calls a new project-spanning route; see Risks), `definitions/sensors/git/pr_ingest.py`, `pr_evaluate.py` (job tag at `:174` uses the assignment id), `evaluate_job.py`, `delivery/results.py:174-182` (`_find_pull_request` uses the task's trigger via assignment). fncli: `dagster/models/trigger_repository.py`, `dagster/backend.py`, `cmds/repository.py`, `cmds/pr.py`, `cmds/verify.py`.
- Baseline blocks for `trigger_repositories`, `project_trigger_repositories`, `pull_request_triggers`.

**Schema, endpoints.** As above.
**Sensors.** Ingest and evaluate loop over active assignments, each polling per assignment as today (the once-per-repository change is stage 7). Delivery finds the trigger by task.

**Tests and commands.** Rewrite `test_trigger_repositories.py` (940 lines; the largest rewrite) in two files, `test_trigger_repositories.py` (global) and `test_project_trigger_repositories.py` (assignments and per-project PRs), and edit `test_triggers.py`, `test_projects.py`, `test_project_lock.py`, `tasks/test_task_from_spec.py`, `conftest.py`; flip the `/trigger_repositories` xfails; add: cross-project loop rejected, `pr_cursor` equals `initial_cursor` with no PRs and max `merged_at` after, RESTRICT blocks assignment delete while triggers exist.
```
cd webserver && ./run_tests.sh ci "tests/test_trigger_repositories.py tests/test_project_trigger_repositories.py tests/test_triggers.py tests/test_projects.py tests/test_project_lock.py tests/tasks/test_task_from_spec.py tests/contract/test_pins.py tests/contract/test_targets.py"
```
Timeout 600000.
```
docker run --rm dagster_test pytest -v app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_backend.py app/tests/test_pr_ingest_sensor.py app/tests/test_pr_evaluate_sensor.py app/tests/test_evaluate_job.py app/tests/test_results_delivery.py
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py tests/test_pr.py tests/test_verify.py tests/test_backend.py
```
Then one webserver call for everything else that shares fixtures: `"tests/test_datasets.py tests/test_results_repositories.py tests/test_results.py tests/test_secrets.py tests/tasks/test_tasks.py"`, timeout 600000.

**Model.** Sonnet. Large but follows stage 2/3 patterns.
**Size.** L (about 1,400 changed lines).
**Risks.** The cursor and initial-cursor validation logic moves and is easy to subtly change (pinned by stage 0 tests). Dagster needs a project-spanning list of active assignments with project ids: add a filtered route (`GET /project_trigger_repositories?active=true`, admin-only, read) rather than looping per project, and document it as the one addition to the ADR's endpoint list (flag in the PR). The `Trigger` polymorphic parent must still be deleted with the child when a trigger is removed (existing behaviour, test it). PR evaluate's job tag moves meaning with the id; tests pin it.
**Done.** All tests above green; zero `xfail` markers for secrets, datasets, results, trigger repositories in `test_targets.py`; `grep -rn "trigger_repository_id" dagster/app` shows only the nested global id; one commit.

---

## Checkpoint A (end of window 1)

**Go to 5 to 7** if: stages 0 to 4 are merged or pushed with green PRs, usage in window 2 covers an XL Opus stage plus about 2 M stages, and the beta demo is not at risk. **Stop here** (merge 0 to 4, defer 5 to 8) if usage is short or any stage needed repeated retries: the result is global resources, per-assignment pull requests (each project still stores its own PR facts and polls per assignment), and the revoke flags are stored and returned but not yet enforced. That is a coherent, shippable state; ADR 0019 is then marked "partly built" in a 5-line edit by hand.

The window-1 report to the owner lists per stage: commit, PR URL, tests run and result, and anything the agent deviated on.

---

## Stage 5. `pull_requests`, fan-out, upsert, backfill, cursors (Opus)

**Goal.** Provider facts stored once per global repository; a trigger per active assignment; two cursors; backfill.

**Files.**
- New `webserver/app/models/pull_request.py`: `pull_requests(id, trigger_repository_id, number, title, raised_by, base_branch, merged_at, merge_commit_sha, changed_files (JSON list of paths))`, `UNIQUE(trigger_repository_id, number)`.
- `webserver/app/models/pull_request_trigger.py`: gains `pull_request_id`; drops duplicated facts (`number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`), these become properties through `pull_request`; unique `(project_trigger_repository_id, pull_request_id)`; keeps `state`, `state_cause`, `spec_raw`, `task_id`.
- New `webserver/app/helpers/pull_request_fanout.py`: `store_pull_request(...)` (upsert) and `fan_out(pull_request, assignments)`; `backfill(assignment)`. Matching reads stored `base_branch` and `changed_files` against the assignment's `base_branch` and `watch_dir` (reuse the matching rule from `dagster/app/definitions/sensors/git/pr_parser.py` and the evaluate step; the agent reads both and states in its report where the matching now lives; the per-trigger spec is still parsed in Dagster evaluate). No match gives `IGNORED`.
- `webserver/app/trigger_repositories_api.py`: new global routes `GET /trigger_repositories/<id>/pull_requests` (paged), `POST .../pull_requests/batch` (upsert plus fan-out, idempotent; 201 with created and existing numbers); the stage 4 per-assignment batch endpoint stays but becomes upsert plus fan-out to all active assignments (removed in stage 7); the per-project PR routes now join `pull_request`.
- Cursors: global cursor `max(pull_requests.merged_at)` for the repository (new field on the global DTO, `pr_cursor`); assignment `pr_cursor` is where its fan-out starts: set at creation to the latest stored PR's `merged_at`, overridable by `initial_cursor` (earlier allowed now, which triggers backfill).
- Backfill triggers: assignment created, re-enabled, un-revoked, `initial_cursor` moved earlier. Hooks go in the PATCH and POST handlers for assignments.
- `webserver/app/dtos/trigger_repository.py`: `PullRequestDTO` (facts), `PullRequestTriggerDTO` assembled from both.
- Dagster and fncli models: `models/pull_request.py` (new), `pull_request_trigger.py`, `backend.py` (`create_pull_requests_batch` still posts per assignment; global post added but unused until stage 7).
- Baseline `pull_requests`, `pull_request_triggers`.

**Tests and commands.** New `webserver/tests/test_pull_requests.py` and `test_fanout.py`; edit `test_project_trigger_repositories.py`, `test_trigger_repositories.py`, `test_triggers.py`, `conftest.py`; delete the "duplicate returns 400" pin; flip the `pull_requests` xfails. Required tests (the invariants):
1. Re-posting the same batch is a no-op (no extra `pull_requests`, no extra triggers).
2. Two projects on one repository each get exactly one trigger per PR.
3. Backfill creates triggers exactly for PRs at or after the assignment's cursor, none twice, on create, on enable, on un-revoke, and when `initial_cursor` moves earlier.
4. Disabled/revoked assignments get no trigger at fan-out; the PR merged while inactive is backfilled on re-enable.
5. A PR touching no `watch_dir` file produces an `IGNORED` trigger per active assignment.
6. Global cursor equals the max `merged_at`; assignment cursor is independent of it.
7. Deleting an assignment is refused while triggers exist.
```
cd webserver && ./run_tests.sh ci "tests/test_pull_requests.py tests/test_fanout.py tests/test_project_trigger_repositories.py tests/test_trigger_repositories.py tests/test_triggers.py tests/contract/test_pins.py tests/contract/test_targets.py"
docker run --rm dagster_test pytest -v app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_backend.py app/tests/test_pr_ingest_sensor.py
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py tests/test_pr.py
```
Timeout 600000 on the webserver call.

**Model.** **Opus**, the only one. Reason: exactly-once semantics across upsert, fan-out and four backfill triggers, and two cursor meanings, where a wrong boundary (`>` versus `>=` on `merged_at`, ties on the same timestamp) loses or duplicates triggers without failing a simple test. If usage forbids Opus, Sonnet with the seven invariants above, and review by the owner.
**Size.** XL (about 900 changed lines, dense).
**Risks.** `merged_at` ties: define the cursor boundary on `(merged_at, number)` and test it. Concurrent ingest posts (two ticks): rely on the unique constraint and `ON CONFLICT`, not check-then-insert. `changed_files` size for very large PRs (store paths only, no content). The matching rule must stay identical to today's Dagster evaluate or PRs flip between `IGNORED` and evaluated.
**Done.** All seven invariants green; xfails flipped; one commit.

---

## Stage 6. `enabled` and `revoked` behaviour

**Goal.** Enforce the flags exactly as decided: sensors and launcher skip inactive assignments; delivery and sync keep resolving inactive rows by id; revoke is immediate and in-flight deliveries fail with a recorded error.

**Files.**
- Dagster `definitions/sensors/git/pr_evaluate.py`, `pr_ingest.py` (still per assignment, filter `active`), `definitions/sensors/task/launcher.py` (active dataset assignment, else fail the task with a clear `state_cause`/error rather than run), `delivery/results.py` (`__call__` gets the task's results assignment; if not active, `patch_result` with `error="results repository access revoked"`, `state=FAILED`; replaces the unpack at `backend.py:189`; `_find_pull_request` handles an inactive trigger assignment, which it must still resolve), `pull_request_sync.py` (keeps resolving inactive rows).
- `dagster/app/backend.py`: `active` on all assignment models (already parsed from stage 2 to 4 DTOs; this stage uses them).
- Webserver: revoke and un-revoke PATCH (admin-only), no lock needed; `Project.in_flight_task_ids` untouched; `resolve_dataset` already checks active (stage 2); verify `POST /tasks` rejects an inactive dataset.
- fncli: models already carry flags; nothing else here.

**Tests and commands.** New cases only: `app/tests/test_results_delivery.py` (revoked results repository fails with the recorded error and does not raise), `test_task_launcher.py`, `test_pr_evaluate_sensor.py`, `test_pr_ingest_sensor.py`, `test_results_pull_request_sync.py` (revoked row still resolved), webserver `test_project_trigger_repositories.py`, `test_results_repositories.py`, `test_datasets.py` for revoke flows, flip the "revoked assignment returned with flags" xfail.
```
cd webserver && ./run_tests.sh ci "tests/test_project_trigger_repositories.py tests/test_results_repositories.py tests/test_datasets.py tests/tasks/test_tasks.py tests/contract/test_targets.py"
docker run --rm dagster_test pytest -v app/tests/test_results_delivery.py app/tests/test_task_launcher.py app/tests/test_pr_evaluate_sensor.py app/tests/test_pr_ingest_sensor.py app/tests/test_results_pull_request_sync.py
```
**Model.** Sonnet. Behaviour is fully specified; no new design.
**Size.** M.
**Risks.** Hiding inactive rows by accident in a list endpoint (pinned by the target contract). A task left `SUCCESS` without result forever after revoke: the delivery failure must set the result `FAILED` so a manual relaunch works (existing behaviour, test it). Evaluate on a revoked trigger must not create new tasks but must still resolve existing triggers.
**Done.** Tests green; flip done; one commit.

---

## Stage 7. Ingest polls once per global repository

**Goal.** Each global repository is polled once, with its own secret, using the global cursor; results post to the global batch endpoint.

**Files.**
- `dagster/app/definitions/sensors/git/pr_ingest.py`: list global trigger repositories that have at least one active, unlocked-project assignment; for each, poll with the global `pr_cursor`, using the repository's `base_branch` (the union of the assignments' base branches is wider than one poll: poll with no base filter, store `base_branch` per PR, fan-out matches; the agent confirms `get_new_merged_pulls` can return the PR's base branch and changed files, else extends `github.py`/`gitea.py` minimally and covers it in `test_github.py`/`test_gitea.py`), then `POST /trigger_repositories/<id>/pull_requests/batch`.
- `dagster/app/backend.py`: `get_global_repositories()`, `create_pull_requests_batch(global_id, ...)`; remove the per-assignment batch call.
- `webserver/app/trigger_repositories_api.py`: delete the per-assignment batch endpoint kept in stage 5.
- fncli `cmds/pr.py` if it posts a batch (check).
- Locked projects: ingest no longer skips by project lock (one poll serves all); fan-out creates triggers only for unlocked... decision: fan-out creates triggers regardless of lock and evaluation/launch are what the lock pauses (matches stage 6 sensors). The agent states this in the PR.

**Tests and commands.** Rewrite `test_pr_ingest_sensor.py` (one poll per repository with two assignments; the global cursor used; assignments of a locked project do not stop the poll), edit `test_backend.py`, `test_github.py`/`test_gitea.py` if extended; webserver: delete the stage 5 batch-per-assignment tests.
```
docker run --rm dagster_test pytest -v app/tests/test_pr_ingest_sensor.py app/tests/test_backend.py app/tests/test_github.py app/tests/test_gitea.py app/tests/test_github_parity.py
cd webserver && ./run_tests.sh ci "tests/test_pull_requests.py tests/test_project_trigger_repositories.py"
```
**Model.** Sonnet.
**Size.** S to M.
**Risks.** Provider API rate and base-branch filters: today `get_new_merged_pulls(base_branch=...)` filters at the provider; polling without it can fetch more. Acceptable, but it must be stated in the PR. The lock behaviour change above.
**Done.** Tests green; no per-assignment batch endpoint left; one commit.

---

## Stage 8a. fncli (Sonnet)

**Goal.** fncli speaks global create plus assign.

**Files.** `scripts/fncli/dagster/backend.py` (about 40 percent: secret, dataset, repository helpers become global create plus assign), `cmds/secret.py`, `cmds/repository.py`, `cmds/dataset.py`, `cmds/common.py` (secret label naming now global), `cmds/project.py`, light edits to `cmds/pr.py`, `cmds/verify.py`; `scripts/get_project.sh`, `scripts/init_repo.sh`; `dev.db/uc1_make_seed.sh`, `dev.db/dataset_password.sh`, `scripts/run_uc1_local.sh` (seed flow).

**Tests and commands.** Edit `test_backend.py`, `test_dataset.py`, `test_config.py`, `test_pr.py`, `test_verify.py`.
```
cd scripts/fncli && python -m pytest -v tests/test_backend.py tests/test_dataset.py tests/test_config.py tests/test_pr.py tests/test_verify.py tests/test_contract_models.py
```
**Model.** Sonnet. **Size.** M. **Risks.** Seed scripts are not covered by tests; the agent edits them but does not run them (they need a cluster), and lists them in the PR as unrun. **Done.** fncli tests green; one commit.

## Stage 8b. openapi, docs, ADR updates (Haiku)

**Goal.** Docs and API description match the code.

**Files.** `webserver/app/static/openapi.json` (secrets, trigger and results repositories, datasets, assignment routes, PR routes; generated by hand from the routes, then validated with `python -c "import json; json.load(open(...))"`), `docs/architecture/entities.md` and `flows.md` (ER diagram, composite-FK paragraph), ADR status lines: 0019 to "Accepted / built", 0003 and 0004 superseded, 0001, 0006, 0007, 0009, 0013, 0015 amended with one line each, `project/handover/README.md` state section, `scripts/fncli/README.md` and `EXAMPLES.md`. No code.

**Tests.** `./run_tests.sh ci "tests/test_main.py"` (openapi is served by `main.py`; one file, timeout 150000) and the JSON parse above.
**Model.** Haiku: mechanical transcription from code that is already written. **Size.** M, mostly volume. **Risks.** openapi drifting from the real shapes (the fixtures in `webserver/tests/contract_fixtures/` are the reference; the agent copies shapes from them, not from memory). **Done.** JSON valid, `test_main.py` green, one commit.

---

## 5. Subagent briefs

Paste the **Common preamble** and then one stage block. Replace `<prev>` with the previous stage's branch.

### Common preamble

```
You are building one stage of ADR 0019 (global resources, shared pull requests) in
Aridhia-Open-Source/PHEMS_federated_node. Docs and code live in the repo at
/home/georgeeddie/Development/Aridhia-Open-Source/PHEMS/PHEMS_federated_node, which is a
main checkout on another branch: NEVER switch it. Work only in your own worktree.

Read first: project/decisions/0019-*.md, project/handover/moonshot-plan.md (your stage and
sections 1-2), and the code your stage touches. project/handover/moonshot-review.md is
model-generated: verify any line reference you rely on.

Rules:
- Create your worktree: git fetch origin <prev> && git worktree add -b <your-branch>
  ../fn-worktrees/moonshot/<name> origin/<prev>. Work there only.
- No flat compatibility API. Global resources at /trigger_repositories, /results_repositories,
  /datasets, /secrets; per-project assignments at /projects/<id>/<kind> with the global
  resource nested. Fail fast, no defensive defaults, copy existing patterns, top-level
  imports only (except tests), do not auto-fix line length.
- Migrations: edit webserver/migrations/versions/001_baseline.py in place; no new revision.
- Keep Dagster and fncli green in the same commit: update the models/backend/sensors that read
  any response you change, and the fixtures (UPDATE_CONTRACT_FIXTURES=1, then
  scripts/sync_contract_fixtures.sh).
- Tests: run ONLY the files listed for your stage, in the foreground, with a bash timeout
  sized at about 2 minutes per file (max 600000). webserver/run_tests.sh ci takes ONE pytest
  argument: pass several files as one quoted string, e.g.
  cd webserver && ./run_tests.sh ci "tests/a.py tests/b.py".
  Never run whole suites, never poll logs, never watch or re-run CI. If a test fails, rerun
  only that test once at most, then STOP and report the failing test and message.
- Do not touch whitelisted_images, the Gitea mirror (ADR 0020), the chart, or
  dagsterApiGrpcArgs.
- Do not widen scope. If the plan and the ADR disagree, follow the ADR and say so.
- Commit once (one commit for the stage), message ending with exactly:
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  (use the model you are actually running as). Do not commit until
  your stage's test list is green. Push with git push -u origin <your-branch>.
- Open a PR: gh pr create --base <prev> --title "<stage title>" with a short body, ending with
  exactly: 🤖 Generated with [Claude Code](https://claude.com/claude-code)
- Final report, five lines max: PR URL, tests run and result, deviations from the plan,
  anything unrun, anything you want the owner to decide.
```

### Stage 0 block (model: sonnet)

```
Stage 0, branch moonshot/s0-contracts, base origin/dagster-moonshot, PR base dagster-moonshot.
Title: "Moonshot stage 0: contract tests".
Do: plan section "Stage 0". Add webserver/tests/contract/{helpers,test_pins,test_targets}.py,
webserver/tests/contract_fixtures/*.json, dagster/app/tests/test_contract_models.py,
scripts/fncli/tests/test_contract_models.py, scripts/sync_contract_fixtures.sh. No source edits
under webserver/app, dagster/app, scripts/fncli outside tests. Pins pass; target shapes are
xfail(strict=True, reason="stage N"). Old-shape tests carry a comment naming the stage that
deletes them.
Tests: cd webserver && ./run_tests.sh ci "tests/contract/test_pins.py tests/contract/test_targets.py" (timeout 240000);
docker build dagster -f dagster/build/test.Dockerfile -t dagster_test && docker run --rm dagster_test pytest -v app/tests/test_contract_models.py;
cd scripts/fncli && python -m pytest -v tests/test_contract_models.py
```

### Stage 1 block (sonnet)

```
Stage 1, branch moonshot/s1-secrets, base moonshot/s0-contracts. Title: "Moonshot stage 1: global secrets".
Do: plan section "Stage 1": drop project_id from secrets, UNIQUE(label), drop composite FKs,
/secrets API (admin-only create/delete, rotation exempt from the lock, delete 409 while used),
new key rule, the three secret_label resolvers, SecretDTO, delete_project must not touch
secrets or call SecretProvider.delete, fold 002 into 001 and delete 002, Dagster and fncli
Secret models, conftest secret fixture. Flip the /secrets xfails.
Tests: ./run_tests.sh ci "tests/test_secrets.py tests/test_dataset_secrets.py tests/test_projects.py tests/contract/test_pins.py tests/contract/test_targets.py" (600000), then
"tests/test_trigger_repositories.py tests/test_results_repositories.py tests/test_datasets.py" (360000);
dagster: app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_secrets.py; fncli: tests/test_contract_models.py tests/test_backend.py.
```

### Stage 2 block (sonnet)

```
Stage 2, branch moonshot/s2-datasets, base moonshot/s1-secrets. Title: "Moonshot stage 2: global datasets".
Do: plan section "Stage 2": global datasets (no project_id), project_datasets, composite FK
(project_id, default_dataset_id), remove the post_update cycle, resolve_dataset/Task.validate/
NewTaskDTO.from_spec check active assignment, task_specs.dataset_id and tasks.task_spec_id
RESTRICT, DAR takes project_id, /datasets and /projects/<id>/datasets endpoints, require_all_drained
for global edits/deletes, first assignment becomes default, delete_project removes assignments only,
Dagster Dataset model + launcher.py:35 project dataset lookup, fncli dataset helpers. Flip xfails.
Tests: webserver "tests/test_datasets.py tests/test_dataset_secrets.py tests/test_projects.py tests/test_project_lock.py tests/tasks/test_tasks.py tests/tasks/test_task_from_spec.py tests/contract/test_pins.py tests/contract/test_targets.py" (600000),
then "tests/test_trigger_repositories.py tests/test_results_repositories.py tests/test_results.py tests/test_dtos.py" (480000);
dagster: app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_task_launcher.py app/tests/test_backend.py;
fncli: tests/test_contract_models.py tests/test_dataset.py tests/test_backend.py.
```

### Stage 3 block (sonnet)

```
Stage 3, branch moonshot/s3-results-repos, base moonshot/s2-datasets. Title: "Moonshot stage 3: global results repositories".
Do: plan section "Stage 3": global results_repositories, project_results_repositories
(UNIQUE project_id), results.results_repository_id -> assignment, /results_repositories global
CRUD + /projects/<id>/results_repositories (inactive row still returned with flags), ResultDTO
gains project_id, check_no_loop results side on assignments (cross-project loops forbidden),
healthcheck, delete_project, Dagster backend/delivery/pull_request_sync.py:49, fncli models.
Flip xfails.
Tests: webserver "tests/test_results_repositories.py tests/test_results.py tests/test_project_lock.py tests/test_projects.py tests/contract/test_pins.py tests/contract/test_targets.py" (600000);
dagster: app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_backend.py app/tests/test_results_delivery.py app/tests/test_results_pull_request_sync.py;
fncli: tests/test_contract_models.py tests/test_backend.py.
```

### Stage 4 block (sonnet)

```
Stage 4, branch moonshot/s4-trigger-repos, base moonshot/s3-results-repos. Title: "Moonshot stage 4: global trigger repositories".
Do: plan section "Stage 4": global trigger_repositories, project_trigger_repositories,
pull_request_triggers FK -> assignment with RESTRICT (still holds PR facts this stage),
/trigger_repositories global CRUD, /projects/<id>/trigger_repositories assignments, per-project
PR routes under the assignment, cursor logic on the assignment, check_no_loop complete (cross-project
loops forbidden), healthcheck, delete_project, a project-spanning active-assignments route for
Dagster, Dagster models/backend/ingest/evaluate/evaluate_job/delivery _find_pull_request, fncli.
Sensors still poll per assignment. Flip xfails.
Tests: webserver "tests/test_trigger_repositories.py tests/test_project_trigger_repositories.py tests/test_triggers.py tests/test_projects.py tests/test_project_lock.py tests/tasks/test_task_from_spec.py tests/contract/test_pins.py tests/contract/test_targets.py" (600000),
then "tests/test_datasets.py tests/test_results_repositories.py tests/test_results.py tests/test_secrets.py tests/tasks/test_tasks.py" (600000);
dagster: app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_backend.py app/tests/test_pr_ingest_sensor.py app/tests/test_pr_evaluate_sensor.py app/tests/test_evaluate_job.py app/tests/test_results_delivery.py;
fncli: tests/test_contract_models.py tests/test_pr.py tests/test_verify.py tests/test_backend.py.
Report when finished; the owner decides at Checkpoint A whether stages 5-8 run.
```

### Stage 5 block (opus)

```
Stage 5, branch moonshot/s5-pull-requests, base moonshot/s4-trigger-repos. Title: "Moonshot stage 5: shared pull requests, fan-out and backfill".
Model: Opus (exactly-once fan-out, backfill and two cursors).
Do: plan section "Stage 5". New pull_requests table (facts + base_branch + changed_files),
pull_request_triggers keeps evaluation state and gains pull_request_id, store_pull_request upsert
and fan_out/backfill in webserver/app/helpers/pull_request_fanout.py, global PR routes and batch
(idempotent), per-assignment batch kept as upsert+fan-out until stage 7, global and assignment
cursors (cursor boundary on (merged_at, number)), backfill on assignment create/enable/un-revoke/
earlier initial_cursor. IGNORED when no match. Seven invariant tests in the plan are mandatory.
Tests: webserver "tests/test_pull_requests.py tests/test_fanout.py tests/test_project_trigger_repositories.py tests/test_trigger_repositories.py tests/test_triggers.py tests/contract/test_pins.py tests/contract/test_targets.py" (600000);
dagster: app/tests/test_contract_models.py app/tests/test_models.py app/tests/test_backend.py app/tests/test_pr_ingest_sensor.py;
fncli: tests/test_contract_models.py tests/test_pr.py.
Commit trailer: Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com> (or the model you run as).
```

### Stage 6 block (sonnet)

```
Stage 6, branch moonshot/s6-enabled-revoked, base moonshot/s5-pull-requests. Title: "Moonshot stage 6: enabled and revoked behaviour".
Do: plan section "Stage 6": evaluate/launch/ingest sensors filter active assignments; launcher
refuses an inactive dataset assignment with a recorded cause; delivery given an inactive results
assignment records error "results repository access revoked", FAILED, no ValueError;
_find_pull_request and pull_request_sync still resolve inactive rows; revoke PATCH is admin-only,
needs no lock; POST /tasks rejects an inactive dataset. Flip the revoked-flags xfail.
Tests: webserver "tests/test_project_trigger_repositories.py tests/test_results_repositories.py tests/test_datasets.py tests/tasks/test_tasks.py tests/contract/test_targets.py" (600000);
dagster: app/tests/test_results_delivery.py app/tests/test_task_launcher.py app/tests/test_pr_evaluate_sensor.py app/tests/test_pr_ingest_sensor.py app/tests/test_results_pull_request_sync.py.
```

### Stage 7 block (sonnet)

```
Stage 7, branch moonshot/s7-ingest-once, base moonshot/s6-enabled-revoked. Title: "Moonshot stage 7: ingest polls each repository once".
Do: plan section "Stage 7": ingest lists global trigger repositories with an active assignment,
polls once each with the repository's secret and the global cursor, stores base_branch and
changed files per PR, posts to POST /trigger_repositories/<id>/pull_requests/batch. Remove the
per-assignment batch endpoint and the Dagster call to it. State the lock behaviour in the PR.
Tests: dagster app/tests/test_pr_ingest_sensor.py app/tests/test_backend.py app/tests/test_github.py app/tests/test_gitea.py app/tests/test_github_parity.py;
webserver "tests/test_pull_requests.py tests/test_project_trigger_repositories.py" (240000).
```

### Stage 8a block (sonnet)

```
Stage 8a, branch moonshot/s8a-fncli, base moonshot/s7-ingest-once. Title: "Moonshot stage 8a: fncli".
Do: plan section "Stage 8a". fncli speaks global create + assign for secrets, datasets,
repositories; update seed scripts but do not run them (list them as unrun).
Tests: cd scripts/fncli && python -m pytest -v tests/test_backend.py tests/test_dataset.py tests/test_config.py tests/test_pr.py tests/test_verify.py tests/test_contract_models.py
```

### Stage 8b block (haiku)

```
Stage 8b, branch moonshot/s8b-docs, base moonshot/s8a-fncli. Title: "Moonshot stage 8b: openapi and docs".
Docs and JSON only, no code. Do: plan section "Stage 8b". Copy response shapes from
webserver/tests/contract_fixtures/*.json, not from memory. Update openapi.json, docs/architecture,
ADR status lines and one-line amendments, handover README state, fncli README and EXAMPLES.
Tests: python -c "import json; json.load(open('webserver/app/static/openapi.json'))";
cd webserver && ./run_tests.sh ci "tests/test_main.py" (150000).
```

## 6. Go/no-go summary

| After | Question | Go | No-go |
|---|---|---|---|
| Stage 0 | Pins green on the preview-equivalent base, Docker works? | Continue | Stop: the environment cannot run tests; fix that first |
| Stage 4 (Checkpoint A) | Usage for an XL Opus stage plus 3 more? Beta safe? | Run 5, 6, 7 (then 8) | Merge 0 to 4 and stop: global resources, per-assignment PRs, flags stored but unenforced |
| Stage 5 | Seven invariants green including backfill and ties? | Continue to 6 | Stop at 4; 5 stays unmerged |
| Stage 7 | Sensors green? | 8a, 8b | Merge to 6; ingest still per assignment |

## 7. Risks across stages

- Test environment: every webserver run needs Docker, Postgres and Keycloak images; Docker Hub rate limits (handover notes `mirror.gcr.io`). First failure of this kind ends the day's run; the agent reports instead of working around it.
- Usage: stage 2 and stage 4 are the heaviest Sonnet stages because of test rewrites (`test_datasets.py` 969 lines, `test_trigger_repositories.py` 940). The brief tells agents to edit fixtures in `conftest.py` first.
- Overlap with open PRs #548, #547, #543, #534, #531, #535 (all already in the base). If any lands differently on `dagster-develop`, rebase before stage 1 only; later stages are stacked.
- Endpoint names for per-project PR routes and the project-spanning active-assignments route are working names; the ADR as updated decides, and the stage 0 target shapes are the place where a mismatch surfaces first.
