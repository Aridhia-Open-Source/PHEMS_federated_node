# As-built: shared-resources and gitea-mirror

> **Status at end of day 2026-10-17. Read this first: the sections below predate some of it.**
> - **Proven live:** the happy path passed end to end on kind-fn (Gitea PR → `YIELDED` → task `SUCCESS` → results PR `OPENED` → `MERGED`), by hand and as the automated test.
> - **GitProvider:** global `GitProvider` (`/global/providers`: `name`, `type` github|gitea, `uri` unique, `api_uri`, `enabled`).
>   - Trigger and results repos are `provider_id` + `repo_path` + `secret_id` (token per repo, for least privilege) + `enabled`, unique `(provider_id, repo_path)`; the `uri` is derived.
>   - A disabled provider makes its repos inactive.
>   - Migration 002. No `upstream_id` yet.
> - **Routes:**
>   - tasks under `/projects/:pid/tasks/...`, plus `GET .../tasks/:id/trigger`
>   - `service-info` deleted
>   - `/global/users`, `/global/registries`, `/global/whitelisted_images`
>   - results under `/projects/:pid/results`
> - **Integrity and project state:**
>   - PRs unique by `(repo, merge_commit_sha)` as well as number (baseline migration)
>   - new projects start **disabled** (baseline migration); fncli `setup-project` enables them at the end. There is no project lock (dropped 2026-10-19): a project is enabled or disabled, a results repository is linked while it is disabled, and enabling may ask for a backfill
> - **Sensors:** one interval for all sensors, `fnDagster.sensors.minIntervalSeconds` (30s default, 2s in dev; PR #554, merged).
> - **Tooling:**
>   - fncli moved into `dagster/fncli` and shares `app.*`; install with `pipx install --force --editable './dagster[cli]'`
>   - Dagster and fncli unit tests run in Docker (`dagster/run_tests.sh`)
>   - e2e: `pytest dagster --e2e [success|failure] -v` from the repo root. The suites are granular (each fncli command and state change is its own test). The failure suite has never been run.
> - **Not built yet:** auth (planned in `project/auth-mvp-plan.md`).
> - **gitea-mirror is parked for the beta.** Post-beta it becomes a stateless mirror service with number-matched PR replay, which the node sees as a `gitea` GitProvider.
> - **To do:** a full refresh of this document, and a narrow bug review (the baseline migration, drain rules, sensors).


- Describes commits: `moonshot/shared-resources` at **95d61117** (local, ahead of origin by 3 fncli commits; worktree `fn-worktrees/moonshot/shared-resources`) and `origin/moonshot/gitea-mirror` at **3b551cb7**.
- Written blind from the code, without the ADRs. Mapped to the IDs in `moonshot-requirements.md`. Paths are relative to the repo root (gitea-mirror paths relative to `gitea-mirror/` as `app/...`).
- The SR sections were first read from `origin/moonshot/shared-resources` (before the fncli move). The dev-tooling and fncli sections (SR-DEV-01, SR-DEV-03, "fncli" under built-but-not-mapped) were re-checked against the local worktree and corrected. Everything else in SR is unchanged by the 3 local commits (checked with `git diff`: only fncli, `scripts/e2e_shared_resources.sh`, `test_live_client_integration.py` and two handover docs differ).
- Not run. Test counts (webserver 606, Dagster plus fncli 470 = 346 + 124, mirror 336/365) are as reported, not re-run.
- Shorthand: "drained" and "all drained" were rules that have since been removed (ADR 0008). "active" (link) = global resource `enabled` and link `enabled` and not link `revoked`.

---

# Part 1: shared-resources (SR)

## 3.1 Global resources (SR-GLOB)

### SR-GLOB-01 Resources are global and created only under /global
**Actual behaviour:** Secrets, datasets, trigger repositories and results repositories each have a blueprint with prefix `/global/...`. POST on these takes no project. Sending `project_id` (and for repos `watch_dir`, `base_branch`, `target_dir`) is a 400 that points to the PUT link route. There is no create route for these resources under `/projects`.
**Evidence:**
- `webserver/app/secrets_api.py:32` prefix `/global/secrets`; `datasets_api.py:31` `/global/datasets`; `trigger_repositories_api.py:36` `/global/repositories/triggers`; `results_repositories_api.py:27` `/global/repositories/results`.
- `datasets_api.py:49-55` `_reject_project`: 400 if body has `project_id`.
- `trigger_repositories_api.py:147-151`: 400 if body has `project_id`, `watch_dir` or `base_branch`.
- `results_repositories_api.py:83-87`: 400 if body has `project_id` or `target_dir`.
- Create/delete need scope `can_do_admin` (`secrets_api.py:140`, `datasets_api.py:79`, `trigger_repositories_api.py:141`, `results_repositories_api.py:77`). Reads and PATCH on secrets use `can_admin_dataset` (blueprint `before_request`, `secrets_api.py:38-41`); dataset PATCH and repo PATCH use `can_do_admin`.
- Blueprint registration list: `webserver/app/__init__.py:78-93`.
**Tests:** `webserver/tests/test_global_resources.py` (`test_repo_create_invalid`, `test_dataset_create_invalid`, `test_secret_create_invalid`); `webserver/tests/test_smoke.py::test_link_global_trigger_repo_and_get_it_back`; `test_trigger_repositories_and_links.py::test_create_get_and_404`.

### SR-GLOB-02 Secrets are addressed by label; values are never returned
**Actual behaviour:** A secret is addressed in the URL by `label` (`/global/secrets/<label>`). POST and PATCH take `values`; these go to the Kubernetes secret store only. The database row holds label, description, provider, generated `key` (`fn-secret-<label>`), `namespace`, `enabled`. Responses are `SecretDTO`, which has no values field. Audit logging redacts `username`, `password` and `values`.
**Evidence:**
- `secrets_api.py:122-126` list returns `SecretDTO` for all rows (no pagination); `:130` GET by label; 404 via `_get_secret` (`:113-117`).
- `webserver/app/dtos/secret.py:7-16` `SecretDTO` fields: id, label, description, provider, key, namespace, enabled, created_at, updated_at.
- `webserver/app/models/secret.py:74-84` key = `f"{KEY_PREFIX}{label}"`; `:66-72` label must make a valid DNS subdomain with the prefix; `label` column unique (`:25`).
- POST: duplicate label is 409 (`secrets_api.py:160-161`); values written to the store first, then the row (`:174-177`); returns 201.
- PATCH `values` rewrites keys in the store (overwrite) and updates `namespace` (`:203-212`); returns 200.
- DELETE removes project links, the row and the stored secret; 409 while any trigger repo, results repo or dataset uses it (`:227-232`); 204.
- `webserver/app/helpers/wrappers.py:83` redacts `username`, `password`, `values` in audit details.
- Datasets reject `username`/`password` in the body and ask for a `secret_label` (`datasets_api.py:58-64`).
**Tests:** `test_global_resources.py`: `test_secret_create_hides_values_and_duplicate_is_409`, `test_secret_label_valid_forms`, `test_secret_list_get_and_404`, `test_secret_rotate_and_disable`, `test_secret_in_use_cannot_be_deleted`, `test_secret_delete_once_unused_and_repointing_frees_it`; `test_dtos.py::TestDatasetDTO::test_never_exposes_credentials`; `test_healthchecks_all.py::test_secret_absent_from_store_and_values_never_exposed`.

### SR-GLOB-03 Each global resource has its own `enabled`; a disabled secret is refused
**Actual behaviour:** Secrets, datasets, trigger repos and results repos each have an `enabled` column (default true). A disabled secret cannot be named when creating or patching a dataset or repository (400), except the secret that resource already uses. On the Dagster side, `read_secret_value` raises before reading if the secret is disabled, and the task launcher fails a task whose dataset secret is disabled.
**Evidence:**
- `enabled` columns: `models/secret.py:33`; `models/dataset.py:49`; `models/trigger_repository.py` (`enabled`, "Turned on or off for the whole node"); `models/results_repository.py:15`.
- `models/secret.py:56-64` `get_enabled_by_label(label, current_id)`: 400 "Secret ... is disabled" unless it is the current secret.
- Used in: `datasets_api.py:90` (POST) and `:176` (PATCH); `trigger_repositories_api.py:155`, `:197`; `results_repositories_api.py:91`, `:133`.
- PATCH `enabled` on a secret needs all linked projects drained (`secrets_api.py:200`); a values-only rotation is exempt.
- `dagster/app/secrets.py:37-41` `read_secret_value`: `PermissionError` if `not secret.enabled`, before any store read.
- `dagster/app/definitions/sensors/task/launcher.py:48-49`: dataset secret disabled gives cause "The secret of dataset ... is disabled".
- The webserver's own `GitRepositoryMixin.get_token` (`models/git_repository.py:68-73`) does not check `secret.enabled`; the healthcheck still reads a disabled secret (`test_disabled_resource_is_still_checked_and_flagged`).
**Tests:** `test_global_resources.py::test_create_referencing_disabled_secret_is_400`, `test_repo_patch_enabled_secret_and_disabled_own_secret`, `test_dataset_patch_name_secret_and_disabled_secret`, `test_linked_secret_enabled_flag_needs_lock_but_rotation_does_not`; dagster `test_secrets.py` (no disabled case found there); `dagster/app/tests/test_results_delivery.py::test_a_disabled_secret_fails_the_delivery_before_its_token_is_read`; `test_task_launcher.py::test_a_task_whose_dataset_secret_is_disabled_is_failed_with_the_cause`.

### SR-GLOB-04 Datasets are global and addressed by id
**Actual behaviour:** `/global/datasets` list/POST, `/global/datasets/<int:id>` GET/PATCH/DELETE. Names are unique, lowercased and unquoted; a taken name is 409. List is paginated (`page_of`). PATCH and DELETE need all linked projects drained and admin scope. DELETE removes the project links; a dataset a task ran on cannot be deleted (DB RESTRICT, reported as 400 "Error while deleting the record").
**Evidence:**
- `datasets_api.py:42-46` list (`page_of(Dataset.get_all(), DatasetDTO)`), `:80` POST (201), `:120` GET, `:131` DELETE (204), `:155` PATCH (200).
- `datasets_api.py:67-73` name uniqueness 409; `dtos/dataset.py:107-115` lowercases and unquotes name; `models/dataset.py:41` `unique=True`.
- `datasets_api.py:141` and `:169` call `require_all_drained`.
- `datasets_api.py:142-148` delete errors become 400 "Error while deleting the record".
- DTO `DatasetDTO` carries `enabled` and `secret` (`dtos/dataset.py:14-28`).
- Project reaches a dataset by link, keyed by dataset id (`projects_api.py:185-277`).
**Tests:** `test_global_resources.py`: `test_dataset_create_lowercases_and_unquotes_name`, `test_dataset_duplicate_name_is_409_case_insensitive`, `test_dataset_get_list_and_404`, `test_dataset_linked_needs_lock_to_patch_and_delete`, `test_non_integer_or_unknown_id_is_404`; `test_pagination_and_filters.py::test_datasets_list_shape`.

### SR-GLOB-05 Trigger and results repositories are global and unique by URI
**Actual behaviour:** Trigger repos and results repos are separate tables, each with a unique `uri`. The URI is normalised (no scheme, lowercase, default port stripped, no trailing slash or `.git`, must be `host/owner/repo`). A duplicate after normalisation is a 409. `api_uri` must be http(s), carry no credentials and be on the repository's own host (api.github.com for github.com). A repo points to a secret by `secret_label`. A trigger repo and a results repo may share a URI (they are different tables).
**Evidence:**
- `models/trigger_repository.py:23` `uq_trigger_repositories_uri`; `models/results_repository.py:20` `uq_results_repositories_uri`.
- `helpers/git_uri.py:12-27` `normalise_repo_uri`; `:30-46` `validate_api_uri`; applied by `@validates` in `models/git_repository.py:41-52`.
- `trigger_repositories_api.py:167-168` and `results_repositories_api.py:103-104`: duplicate is 409.
- Provider restricted to values of `GitProvider` (`models/git_repository.py:51`).
- DELETE needs all linked projects drained; link rows go with it; refused while PRs were ingested (trigger) or results exist (results) via DB RESTRICT, shown as 400 (`trigger_repositories_api.py:126-136`, `results_repositories_api.py:62-71`).
- PATCH accepts only `provider`, `api_uri`, `secret_label`, `enabled`; `uri` cannot change; only a `secret_label`-only patch skips the drain check (`trigger_repositories_api.py:187-194`).
**Tests:** `test_global_resources.py`: `test_repo_uri_normalised_on_create`, `test_repo_duplicate_is_409_after_normalisation`, `test_repo_non_default_port_is_kept_and_distinct`, `test_repo_custom_api_uri_on_repo_host_accepted`, `test_repo_patch_invalid`, `test_linked_repo_needs_lock_to_delete_or_disable`; `test_git_uri.py`; `test_trigger_repositories_and_links.py::test_global_patch_and_delete_need_every_linked_project_drained`, `test_secret_rotation_is_exempt_from_the_lock`; `test_results_and_delivery.py::test_global_results_repo_create_get`.

---

## 3.2 Project links (SR-LINK)

### SR-LINK-01 A project links to a resource with PUT, keyed by the global id
**Actual behaviour:** Each resource has `PUT /projects/<pid>/<kind>/<global key>`: datasets by dataset id, secrets by label, trigger and results repositories by repository id. PUT returns 201 on first link and 200 when a link already exists (replacing the link's settings). GET, PATCH and DELETE use the same key. 404 if the global resource or the link does not exist.
**Evidence:**
- Datasets: `projects_api.py:208-234` (PUT), `:198` GET, `:237` PATCH, `:265` DELETE; list `:185`.
- Secrets: `projects_api.py:310-338`, `:300`, `:341`, `:369`; list `:287`.
- Results repos: `projects_api.py:419-458` (201 or 200 at `:458`), `:409`, `:461`, `:497`; list `:396`.
- Trigger repos: `project_trigger_repositories_api.py:78-138` (201 at `:138`, 200 at `:117`); GET `:141`; PATCH `:151`; DELETE `:202`; list `:62`.
- `_link` helper finds a link by the resource id; missing link is 404 (`projects_api.py:165-172`); trigger `_assignment` `:43-50`.
- PUT bodies: datasets/secrets `{enabled}`; results `{target_dir, owned_by_federated_node, enabled}`; trigger `{watch_dir, base_branch, enabled}`. Unknown fields are 400.
- Re-PUT on an existing link needs drained (dataset `:231`, secret `:335`, trigger `:105`); linking a results repository needs the project disabled (409 otherwise), even the first link. The first link of a dataset, secret or trigger repo has no such rule.
**Tests:** `test_trigger_repositories_and_links.py::test_link_201_lists_and_active_filter`, `test_link_put_errors`, `test_relink_put_changes_settings_and_disables`, `test_link_lifecycle_gates`; `test_projects_api.py::test_secret_link_get_list_and_errors`, `test_dataset_link_get_list_and_errors`, `test_first_trigger_link_needs_no_lock`; `test_results_and_delivery.py::test_link_needs_lock_then_relink_replaces_settings`, `test_relink_needs_drained_project`.

### SR-LINK-02 `enabled`, `revoked` and `active` behave as defined
**Actual behaviour:** Every link row has `enabled` (set by a person, default true) and `revoked` (set only by an admin, default false). `active` is computed, not stored: global `enabled` AND link `enabled` AND NOT `revoked`. DTOs expose `enabled`, `revoked`, `active`. PATCH of `enabled` needs the project drained. PATCH of `revoked` needs admin and no drain. A non-admin sending `revoked` gets 403.
**Evidence:**
- `models/project_dataset.py:37`, `models/project_secret.py:37`, `models/project_trigger_repository.py:61`, `models/project_results_repository.py:51`: `active` properties.
- Columns: `enabled` / `revoked` (e.g. `models/project_secret.py:18,21`).
- PATCH rules: datasets `projects_api.py:254-262` (`g.caller_is_admin` check at `:254`; `require_drained` only if `enabled` in body, `:257-258`); same pattern for secrets `:358-363`, results `:479-483`, triggers `project_trigger_repositories_api.py:169-173`.
- Fields must be booleans (400 otherwise).
- `g.caller_is_admin` is set in `helpers/wrappers.py:32`.
- DTOs: `ProjectDatasetDTO` `dtos/dataset.py:51-67`, `ProjectSecretDTO` `dtos/secret.py:19-35`, `ProjectTriggerRepositoryDTO` `dtos/trigger_repository.py:43-69`, `ProjectResultsRepositoryDTO`.
- Project `enabled` is separate and not part of link `active` (`models/project.py:22`); see SR-SENS for where it is applied.
**Tests:** `test_trigger_repositories_and_links.py::test_revoke_is_admin_only`, `test_revoke_and_unrevoke_semantics`, `test_active_link_filter_follows_every_flag`, `test_link_settings_patch_with_a_task_in_flight`; `test_projects_api.py::test_link_changes_ignore_tasks_in_flight`; `test_results_and_delivery.py::test_revoked_link_listed_inactive_and_other_project_cannot_touch`.

### SR-LINK-03 Revoke takes effect immediately and only on that resource
**Actual behaviour:** Revoking PATCHes `revoked: true` on one link. It changes only that link's `active`; `enabled` is untouched, so un-revoking restores the earlier state. For trigger links, un-revoking (or enabling) an active link runs a backfill of missed PRs. Results and dataset effects are read at the time of use (see SR-RES-06, SR-SENS-08).
**Evidence:**
- No `require_drained` when only `revoked` is in the body: `projects_api.py:257` (`if "enabled" in body`), `:482` (`set(body) - {"revoked"}`); `project_trigger_repositories_api.py:172`.
- Column comment: "Never touches enabled, so a re-grant restores the previous state" (`models/project_dataset.py:19-20`).
- Backfill after becoming active: `project_trigger_repositories_api.py:175,196-198`.
- Revoked link stays listed with flags (`projects_api.py:190-195`).
**Tests:** `test_trigger_repositories_and_links.py::test_revoke_and_unrevoke_semantics`; `test_pull_requests_and_tasks.py::test_unrevoke_backfills_what_was_missed`; `test_projects_api.py::test_link_changes_ignore_tasks_in_flight`.

### SR-LINK-04 Link uniqueness
**Actual behaviour:** Each link table has a unique constraint on (project, resource): datasets, secrets, trigger repos. The results link is unique on `project_id` alone, so a project has at most one results repository link. A second, different results repo on the same project is 409. The same results repo may be linked to many projects.
**Evidence:**
- `models/project_dataset.py:24` `uq_project_datasets_project_dataset`; `models/project_secret.py:24` `uq_project_secrets_project_secret`; `models/project_trigger_repository.py:49` `uq_project_trigger_repositories_project_repo`.
- `models/project_results_repository.py:17` `unique=True` on `project_id`.
- `projects_api.py:444-446`: other repo already linked gives 409 "already has a results repository".
- Re-PUT of the same pair updates the link instead of failing (`:448-458`).
**Tests:** `test_results_and_delivery.py::test_one_results_repo_per_project_but_repo_shared`; `test_trigger_repositories_and_links.py::test_two_projects_link_one_repo_independently`.

### SR-LINK-05 Loops across projects are forbidden
**Actual behaviour:** When a results link or a trigger link is created or changed, `check_no_loop(uri)` loads all results links and trigger links (any project) whose repository has that URI. It refuses (400) when the trigger watches the whole repository, or when the trigger `watch_dir` and the results `target_dir` overlap as path prefixes. The change is rolled back. Directories are normalised; `..` is refused.
**Evidence:**
- `helpers/repository_loop.py:30-52` `check_no_loop`; `:8-19` `normalise_dir`; `:22-27` overlap = one is a prefix of the other.
- Called after flush, with rollback on failure: results `projects_api.py:387-393`, `:456`, `:492`; triggers `project_trigger_repositories_api.py:53-59`, `:111`, `:132`, `:192`.
- Not called on creating the global repositories themselves.
**Tests:** `test_results_and_delivery.py::test_results_dir_inside_watched_dir_refused`, `test_watch_dir_over_results_dir_refused_and_other_repo_or_project`, `test_link_target_dir_validation`, `test_link_target_dir_normalised_and_never_absolute`.

### SR-LINK-06 Dataset links and the default dataset
**Actual behaviour:** The first dataset linked to a project becomes `projects.default_dataset_id`; later ones do not replace it. A composite FK ties the default to the project's own link. Deleting that link sets the default to NULL. A task naming a dataset needs a link to it that is active; a task naming none uses the default, which must also be active; a task may have none. A dataset link has no settings besides `enabled`/`revoked`.
**Evidence:**
- `models/project_dataset.py:40-49` (`add`: sets default if None); `:50-57` (`delete`: clears default).
- `models/project.py:35-38` composite FK `fk_projects_default_dataset` (`id`, `default_dataset_id`) to `project_datasets`.
- `models/project.py:104-124` `resolve_dataset`: named dataset must be assigned (400 "does not belong to project") and active (400 "not active"); no name and no default returns None.
- `dtos/task.py:49` `NewTaskDTO.from_spec` calls `resolve_dataset`.
- `ProjectTriggerRepositoryDTO.dataset_id` is the project's default (`models/project_trigger_repository.py` `dataset` property; DTO `:63`).
- `projects_api.py:198-277` dataset link routes; DELETE unlink needs drained.
**Tests:** `test_projects_api.py::test_dataset_link_disable_unlink_and_default_dataset`; `test_pull_requests_and_tasks.py::test_dataset_default_and_case_insensitive_override`, `test_unusable_dataset_rejects_the_pr`; `tasks/test_task_from_spec.py::TestNewTaskDTOFromSpec` (override, other project, inactive, disabled default, no dataset); `test_trigger_repositories_and_links.py::test_dataset_link_has_no_settings`, `test_dataset_unlink_by_task_status`.

### SR-LINK-07 Deleting a project removes links only
**Actual behaviour:** `DELETE /projects/<id>` works in any project state. It deletes the project's tasks, dataset links, triggers (PR and API), trigger links, secret links and results links, then the project. Global datasets, secrets, repositories, their stored values and the shared `pull_requests` rows are left. On any failure it rolls back and returns 400. Returns 204.
**Evidence:**
- `projects_api.py:120-162`: `require_drained` at `:133`; deletes in order `:139-156`; 204 at `:162`.
- Comment: "Secrets, datasets and results repositories belong to no project: they, and their stored values, are left alone" (`:126-128`).
- `models/project.py:56-58` `triggers` relationship with `cascade="all, delete"`, `passive_deletes=True`.
**Tests:** `test_projects_api.py::test_delete_is_soft_hides_the_project_and_frees_name`, `test_delete_blocked_by_task_in_flight`, `test_delete_cascades_links_but_keeps_global_resources`, `test_delete_removes_tasks_and_project_prs_but_keeps_global_prs`.

---

## 3.3 Pull requests and triggers (SR-PR)

### SR-PR-01 Batch ingest stores PRs once and is idempotent
**Actual behaviour:** `POST /global/repositories/triggers/<id>/pull_requests` takes `{"pull_requests": [...]}` (max 100, else 400; each item validated strictly, one bad item refuses the whole batch). Each PR is stored once per (repository, number) with `INSERT ... ON CONFLICT DO NOTHING`; its changed file paths and statuses are stored. A stored PR's facts are never changed. Response 201 with `created` and `existing` number lists. A disabled repository is 400 and stores nothing.
**Evidence:**
- `trigger_repositories_api.py:91-116`: disabled check `:101-102`, list check `:104-105`, cap `:108-109`, response `:113-116`.
- `helpers/pull_request_fanout.py:63-89` `store_pull_request` (pg `on_conflict_do_nothing(constraint='uq_pull_requests_repo_number')`); `:92-109` `ingest_pull_requests`.
- `models/pull_request.py:34` `uq_pull_requests_repo_number`; `PullRequestFile` composite PK (`:64-67`).
- `dtos/trigger_repository.py:118-144` `PullRequestRequest`: strict, `extra="forbid"`, `number >= 1`, `merged_at` ISO string to naive UTC.
- Route is marked "called by Dagster only" in a TODO but has the same admin-scope auth as the others (`before_request` `can_admin_dataset`).
**Tests:** `test_pull_requests_and_tasks.py::test_ingest_fans_out_and_is_idempotent`, `test_batch_limit`, `test_invalid_ingest_bodies_are_400_and_store_nothing`, `test_merged_at_formats_and_utc_conversion`, `test_disabled_and_unknown_repository_refuse_ingest`.

### SR-PR-02 Provider facts are stored once per repository
**Actual behaviour:** The `pull_requests` table is keyed to the global trigger repository (not to a project) and holds number, title, raised_by, merge sha, `merged_at`, `base_branch`, `files_truncated`, plus `pull_request_files` (path, status). Many projects watching the repo share these rows. Each project's own state is a separate `pull_request_triggers` row. `GET /global/repositories/triggers/<id>/pull_requests` lists the facts (paginated, merge time newest first).
**Evidence:**
- `models/pull_request.py:15-53` (`PullRequest`), `:56-70` (`PullRequestFile`).
- `models/pull_request_trigger.py:17-48`: `pull_request_id` FK RESTRICT; `project_trigger_repository_id` FK RESTRICT; unique (link, PR) at `:21`.
- `trigger_repositories_api.py:73-87` global list with `page`/`per_page` clamped to at least 1; `PullRequestDTO` (`dtos/trigger_repository.py:72-82`).
- Deleting a link or the global repo is blocked while triggers/PRs exist (RESTRICT), shown as 400.
**Tests:** `test_pull_requests_and_tasks.py::test_two_projects_on_one_repo_are_independent`; `test_projects_api.py::test_delete_removes_tasks_and_project_prs_but_keeps_global_prs`; `test_pagination_and_filters.py::test_pr_list_shape_order_and_paging`.

### SR-PR-03 Fan-out creates one trigger per active, matching link
**Actual behaviour:** After storing new PRs, the webserver creates a `pull_request_triggers` row (state UNKNOWN) for each active link of that repository where the PR matches: same `base_branch` as the link, and either `files_truncated` is true or the PR added a `.json` file under the link's `watch_dir`. Non-matching PRs get no trigger; the cause is logged at info level. Creation uses a savepoint, so a race on the unique constraint skips only that trigger. Fan-out skips a disabled project (`accepts_triggers`).
**Evidence:**
- `helpers/pull_request_fanout.py:112-118` `active_assignments` (link enabled, not revoked, repository enabled); no project filter.
- `unmatched_cause`: base branch mismatch; `files_truncated` returns "matches"; else needs a non-empty `spec_files` (`helpers/spec_files.py`: a file with `is_under_dir`, suffix `.json`, status `"added"`). The same helper fills `spec_files` on the PR trigger DTO, and Dagster's evaluate step trusts it instead of re-fetching the files.
- `:121-160` `create_triggers` (savepoint at `:155`); `:163-166` `fan_out`.
- `helpers/spec_files.py` `is_under_dir`: whole path segments; empty `watch_dir` means the whole repo.
**Tests:** `test_pull_requests_and_tasks.py::test_ingest_fans_out_and_is_idempotent`, `test_file_matching_against_watch_dir`, `test_truncated_file_list_matches_but_base_branch_still_applies`, `test_base_branch_default_override_and_case`, `test_disabled_link_gets_no_trigger_until_enabled`.

### SR-PR-04 Trigger states: UNKNOWN, YIELDED, REJECTED. No IGNORED.
**Actual behaviour:** `TriggerState` has three values: UNKNOWN, REJECTED, YIELDED. `state_cause` is required for REJECTED and forbidden otherwise (model check and DB check constraint). PATCH on a PR trigger sets state through `set_state`. REJECTED is "final" only by convention for task creation (POST task needs UNKNOWN); PATCH itself does not block moving out of REJECTED. No IGNORED in webserver or Dagster code.
**Evidence:**
- `models/trigger_state.py:18-20`; Dagster copy `dagster/app/models/trigger_state.py:13-15`.
- `models/trigger.py:42-48` check constraint `ck_triggers_state_cause_for_rejected` `(state = 'REJECTED') = (state_cause IS NOT NULL)`; `:71-85` `set_state` (invalid state 400; cause rules).
- `project_trigger_repositories_api.py:286-301` PATCH body `state`, `state_cause`.
- `grep IGNORED` finds it only in tests.
**Tests:** `test_triggers.py` (`TestTriggerSetState`, `test_check_ties_state_cause_to_state`); `test_pull_requests_and_tasks.py::test_patch_state_legal_transitions_and_cause`, `test_patch_state_illegal_bodies_are_400_and_change_nothing`.

### SR-PR-05 Cursors, backfill and no replay of history
**Actual behaviour:** A new trigger link records `initial_cursor` and `initial_cursor_number` from the latest stored PR of that repository (or the link's creation time if none). `create_triggers` only considers PRs strictly after the pair (`merged_at`, `number`). So history before linking is not replayed. If a link becomes active later (created enabled, re-enabled, un-revoked), `backfill` creates the triggers it missed since its cursor. The ingest cursor (what Dagster polls from) is the latest stored `merged_at` for the repo, or with none stored the earliest `initial_cursor` among active links of enabled projects.
**Evidence:**
- `project_trigger_repositories_api.py:124-131` cursor set at link creation; `:134-137` backfill if active.
- `models/project_trigger_repository.py:40` `initial_cursor_number`; `:71-80` `get_pull_request_cursor` (latest merge of this link's PRs, else `initial_cursor`).
- `models/trigger_repository.py:31-37` `get_pull_request_cursor`; `:38-48` `get_ingest_cursor` (filters links `a.active and a.project.enabled`).
- `helpers/pull_request_fanout.py:121-160` cursor comparison `merged_at > cursor_at OR (== and number > cursor_number)`; `:169-173` `backfill`.
- Backfill on PUT of existing link (`:113-116`) and PATCH (`:175,196-198`).
- DTO exposes `pr_cursor` on the global repo (ingest cursor) and on the link.
**Tests:** `test_pull_requests_and_tasks.py::test_cursor_rule_link_first_then_ingest`, `test_cursor_with_nothing_stored_is_link_creation_time`, `test_unrevoke_backfills_what_was_missed`, `test_disabled_link_gets_no_trigger_until_enabled`.

### SR-PR-06 Project PR lists filter in the webserver
**Actual behaviour:** `GET /projects/<pid>/repositories/triggers/<rid>/pull_requests` returns the project's triggers for that link, newest merge first, with `page`, `per_page` (default 20, not clamped) and `?state=` (UNKNOWN, REJECTED, YIELDED; other values 400). Response keys: `items`, `page`, `per_page`, `total`, `pages`. Scoped to the link, so another project's link gives 404. Trigger link list supports `?active=true`. The global trigger repo list supports `?active_link=true`.
**Evidence:**
- `project_trigger_repositories_api.py:236-273` (list); `:254-262` state filter; `:264` ordering.
- `:62-75` `?active=true` (filter done in Python over the link query in the webserver).
- `trigger_repositories_api.py:46-61` `?active_link=true` (SQL: repo enabled AND any link enabled, not revoked, project enabled).
- `projects_api.py:60` `GET /projects` filters through `parse_query_params` (e.g. `enabled=true`).
- `GET .../pull_requests/<number>` `:276-283`.
**Tests:** `test_pagination_and_filters.py::test_pr_list_state_filter`, `test_pr_list_state_reflects_patch_and_is_scoped_to_link`, `test_pr_list_sorted_by_merge_time_desc`, `test_trigger_repos_active_link_filter`, `test_projects_filters`; `test_pull_requests_and_tasks.py::test_list_filter_pagination_and_unknown`, `test_trigger_of_other_project_is_404`.

### SR-PR-07 Create a task from a PR
**Actual behaviour:** `POST /projects/<pid>/repositories/triggers/<rid>/pull_requests/<n>/task` with `{"spec_raw": "<string>"}`. If the PR trigger already has a task it returns it (200). Otherwise it needs state UNKNOWN (else 409) and an active link (else 409). The raw spec is stored (max 64 KiB) before parsing. A bad spec marks the trigger REJECTED with the cause, commits, and re-raises the 400. A good spec sets YIELDED and creates the task in one transaction (201). A race on the task unique key returns the existing task (200).
**Evidence:**
- `project_trigger_repositories_api.py:304-351`: idempotent `:318-319`; UNKNOWN check `:320-321`; active check `:322-323`; `spec_raw` must be a string `:326-328`; reject path `:330-339` (cause cut to 1024 chars); success `:341-351`.
- `models/trigger.py:62-69` `set_spec_raw` cap `SPEC_RAW_MAX_BYTES = 64 * 1024` (`helpers/const.py:60`).
- `dtos/task_spec.py:70-85` `from_pr_spec`: JSON with a `spec` object; `image` or `docker_image`; `extra="forbid"`.
- `dtos/task.py:44-58` `NewTaskDTO.from_spec`: name = spec name or PR title; `requested_by` = PR raiser.
- `models/task.py:33` `trigger_id` unique, so one task per trigger.
- Dagster caller: `dagster/app/backend.py:138-151`; `evaluate_job.py:32-57`.
**Tests:** `test_pull_requests_and_tasks.py::test_create_task_yields_pr_and_is_idempotent`, `test_spec_options_are_kept`, `test_bad_spec_rejects_the_pr`, `test_spec_raw_must_be_a_string_and_the_pr_is_not_judged`, `test_only_unknown_triggers_of_an_active_link_get_a_task`, `test_post_task_404s_and_disabled_project`; `test_triggers.py::test_one_task_per_trigger`.

---

## 3.4 Tasks (SR-TASK)

### SR-TASK-01 All task routes live under /projects/:pid/tasks
**Actual behaviour:** The tasks blueprint has prefix `/projects/<int:project_id>/tasks`. Every task route (list, create, validate, get, patch, retry, cancel, results, logs, trigger, approve, block) is under it. A task of another project is 404. There is no `/tasks` route outside `/projects`.
**Evidence:**
- `tasks_api.py:41` prefix; routes `:82-356`; `:74-79` `get_project_task` 404 for another project; `:127-128` GET returns 404 JSON.
- `cancel`, `logs`, `approve`, `block` raise `NotImplementedException` (501): `tasks_api.py:221, 332, 344, 356`.
- `GET .../results` is `:312-322`.
**Tests:** `test_pull_requests_and_tasks.py::test_a_task_of_another_project_is_a_404`, `test_tasks_list_filters_and_pagination`, `test_task_status_lifecycle_fields_and_get`; `tasks/test_patch_task.py`.

### SR-TASK-02 GET /tasks/service-info is deleted
**Actual behaviour:** There is no `service-info` route anywhere in the webserver. The git history has a commit "Delete GET /tasks/service-info" (`1dd09dc4`). `grep service-info` over `.py/.json/.sh/.md` finds nothing.
**Evidence:**
- No `service-info` in `webserver/app/*.py` or `webserver/app/static/openapi.json`.
- `git log` subject: `1dd09dc4 Delete GET /tasks/service-info`.
**Tests:** none found (no test asserts the 404).

### SR-TASK-03 GET /projects/:pid/tasks/:id/trigger returns the task's PR and trigger repository
**Actual behaviour:** Returns `TaskTriggerDTO`: the PR trigger fields (`project_id`, `trigger_repository_id`, `number`, `title`, `raised_by`, `merge_commit_sha`, `merged_at`, `state`, `state_cause`, `task_id`) plus a nested `trigger_repository` `{id, repo_path, uri}`. A task not made by a PR (an API task) is 404. Needs the caller to own the task, be admin, or be the system user. Dagster uses it to build the delivery branch name and title.
**Evidence:**
- `tasks_api.py:297-309`; `dtos/trigger_repository.py:36-40, 85-107`.
- Ownership check `tasks_api.py:52-71` (`does_user_own_task`: requester, admin or system user, else 403).
- Dagster `backend.py:179-183` `get_task_trigger`; `delivery/results.py:195-197`.
**Tests:** `test_pull_requests_and_tasks.py::test_task_trigger_is_the_pull_request_with_its_repository`, `test_task_trigger_of_a_task_made_by_hand_is_a_404`; dagster `test_backend.py::test_get_task_trigger_reads_the_pull_request_and_its_repository`.

### SR-TASK-04 A finished task cannot change status
**Actual behaviour:** `PATCH /projects/<pid>/tasks/<id>` refuses (409) a status change when the current status is SUCCESS, FAILED or CANCELED and the new status differs. Setting the same status again is allowed. Other fields (`executor_run_id`, `exit_code`, `state_cause`, `started_at`, `completed_at`) can still be patched. Unknown fields and invalid status values are 400. Scope is `can_admin_dataset`.
**Evidence:**
- `tasks_api.py:49` `FINAL_STATUSES`; `:135-187` patch; `:158-161` the 409; `:150-152` allowed fields.
- Dagster: run-status sensor treats the 409 as skip (`dagster/app/definitions/sensors/task/run_status.py:58-63`).
**Tests:** `test_pull_requests_and_tasks.py::test_finished_tasks_cannot_change_status`, `test_bad_task_patches_are_400_and_change_nothing`; `tasks/test_patch_task.py`; dagster `test_task_run_status_sensor.py::test_a_409_from_a_finished_task_is_skipped`.

### SR-TASK-05 Retry resets a failed or canceled task
**Actual behaviour:** `POST .../tasks/<id>/retry` works only for FAILED or CANCELED (else 400). It sets status PENDING, adds 1 to `attempt`, and clears `executor_run_id`, `started_at`, `completed_at`, `exit_code`, `state_cause`. Returns 200. The launcher's run key includes the attempt, so a retry gets a new run.
**Evidence:**
- `tasks_api.py:190-211`.
- `dagster/.../launcher.py:58` run key `task/{task.id}/{task.attempt}`.
**Tests:** `test_pull_requests_and_tasks.py::test_retry_resets_a_failed_task_only`; dagster `test_task_launcher.py::test_the_run_key_includes_the_attempt`.

### SR-TASK-06 Create and validate a task through the API
**Actual behaviour:** `POST /projects/<pid>/tasks` (scope `can_exec_task`) takes a TES-like body (`executors[0].image`/`env`, `name`, `tags.dataset_name`, `resources`, `repository`). A disabled project is 409. The request is recorded first as an `ApiRequestTrigger` with the raw body. Validation errors mark it REJECTED with the cause, commit, and re-raise. On success it sets YIELDED and creates the task (201, returns `id`, `api_request_id`, `status`, `created_at`). `POST .../tasks/validate` runs the same validation without creating anything and returns `"Ok"`, 200; it does not check that the project is enabled.
**Evidence:**
- `tasks_api.py:224-277` create (enabled check `:242-243`; record `:247-248`; reject `:261-264`; yield `:266-270`); `:280-294` validate.
- `models/task.py:89-165` `Task.validate`: name required; project resolved; dataset via `resolve_dataset`; image format; optional whitelist (`ENABLE_IMAGE_WHITELIST`); image must exist on the registry (404); CPU/memory limits >= requests.
- `models/api_request_trigger.py:7-29`; `dtos/task_spec.py:48-68` `from_api_body`; env key regex and size cap (`:29-39`).
- If `repository` is given, validation looks for exactly one project link on that URI (`models/task.py:106-116`).
**Tests:** `tasks/test_task_from_spec.py::TestPostTasks` (creates request and task once, invalid env/spec/name keep a rejected request, disabled project, other project's dataset, no executors, unauthenticated); `tasks/test_resource_validators.py`; `test_dtos_task_spec.py`.

---

## 3.5 Results delivery (SR-RES)

### SR-RES-01 Results are project-scoped
**Actual behaviour:** Results routes are under `/projects/<pid>/results`. A result is tied to a task and to the project's own results link (`results.results_repository_id` points to `project_results_repositories.id`, not the global repo). A result whose task is in another project is 404. The API shows the global `results_repository_id`.
**Evidence:**
- `results_api.py:26` prefix `/projects`; `:34-41` `_project_result`; `:44-64` list; `:67-76` get; `:79-124` post; `:127-186` patch.
- `models/result.py:22-27` FK to `project_results_repositories`, unique (task, link) `:17`; `:38-40` `project_id` via link.
- `dtos/result.py:18-23` maps back to the global repository id.
- `tasks_api.py:312-322` `GET .../tasks/<id>/results`.
**Tests:** `test_results_and_delivery.py::test_results_are_scoped_to_their_project`, `test_task_results_route`, `test_list_filter_by_step`; `test_pull_requests_and_tasks.py::test_task_results_list_the_delivery`.

### SR-RES-02 Only a SUCCESS task can have results
**Actual behaviour:** `POST /projects/<pid>/results` with `{task_id, results_repository_id}` (global id; project must be linked, else 400). If a result already exists for (task, link) it is returned (200) regardless of task status. Otherwise a non-SUCCESS task is 409. An inactive link is also 409. Success creates a `PullRequestResult` (201).
**Evidence:**
- `results_api.py:79-124`: lookup `:108-110`; SUCCESS check `:112-113`; active check `:116-120`; create `:122-124`.
- Task must belong to the project (404 otherwise) and the caller must own it (`:96-98`).
- Dagster treats a 409 as "skipped, not failed": `delivery/results.py:67-72`.
**Tests:** `test_results_and_delivery.py::test_post_result_only_for_success_task_and_is_idempotent`, `test_post_result_refusals`; dagster `test_results_delivery.py::test_a_refused_result_is_skipped_not_failed`.

### SR-RES-03 Result progress only moves forward
**Actual behaviour:** A PR result has `step` (UNKNOWN, PUSHED, OPENED, MERGED, CLOSED) and `state` (IN_PROGRESS, DELIVERED, FAILED). `set_step` allows only forward moves by rank (UNKNOWN 0, PUSHED 1, OPENED 2, MERGED and CLOSED 3); nothing can leave MERGED or CLOSED; the same step again is allowed. A refused move is 400. `state` is not constrained beyond being a valid value. PATCH accepts `attempts`, `error` and the PR fields.
**Evidence:**
- `models/pull_request_result.py:11-18` ranks; `:66-78` `set_step`; `models/pull_request_result_step.py`; `models/result_state.py:17-19`.
- `results_api.py:127-186` patch (allowed fields `:28-31`; `step` `:158-159`; `state` `:149-152`).
- Dagster delivery records PUSHED before opening the PR (`delivery/results.py:93`).
**Tests:** `test_results_and_delivery.py::test_step_is_forward_only`, `test_state_changes_freely_but_only_to_valid_values`, `test_patch_all_fields_and_reset_to_null`, `test_patch_invalid_fields_refused_and_nothing_applied`; dagster `test_results_delivery.py::test_pushed_is_recorded_before_the_pull_request_is_opened`, `test_a_result_past_pushed_is_left_alone`.

### SR-RES-04 Delivery pushes a branch and opens a results PR
**Actual behaviour:** When a `k8s_pipes_job` run succeeds, `task_results_delivery_sensor` requests `deliver_results_job` once per (task, attempt). The op reads the task, the project's results link and the PR trigger. It creates the result, clones the results repo, and if the branch is not on the remote it zips `<artifact mount>/<run_id>` (cap `RESULTS_MAX_ZIP_BYTES`, default 10 MiB), writes `results.zip`, `spec.json`, `metadata.json` under `<target_dir>/<trigger repo name>/<PR number>/<task id>/`, commits and pushes branch `<that layout>-<merge sha[:7]>`. It records PUSHED, then opens (or finds) a PR into the clone's default branch, records OPENED (or what the provider says), state DELIVERED, attempts +1. On any failure it records state FAILED, error (max 1000 chars) and attempts +1, then raises. A failed delivery is not retried by itself; a manual relaunch resumes.
**Evidence:**
- `dagster/app/definitions/sensors/task/delivery.py:15-36` op/job; `:39-63` sensor (run key `deliver/{task_id}/{attempt}`, tags `trigger=delivery`, `delivery_task_id`).
- `dagster/app/delivery/results.py:48-116` flow; `:118-177` `_push` (layout `:135-138`; existing branch reused `:144-147`; artifacts dir `:149-151`; size cap `:156-159`; files `:164-175`); `:179-193` `_open_pull_request`.
- `dagster/app/delivery/git_push.py:12-16` committer, 60 s timeout; `:26-37` token sent via env `http.extraHeader`, not on the command line; `:67-72` shallow clone.
- `dagster/app/config.py:37-39` `max_zip_bytes` default 10485760; chart `templates/dagster-env-config.yaml:15,20`.
**Tests:** dagster `test_results_delivery.py` (`test_success_pushes_a_branch_with_the_layout_and_records_pushed_then_opened`, `test_over_the_cap_fails_the_delivery_and_pushes_nothing`, `test_a_git_failure_records_the_error_and_raises`, `test_missing_artifacts_fail_the_delivery`, `test_a_retry_from_pushed_skips_the_push_and_opens_its_pull_request`, `test_the_token_stays_out_of_the_command_line`, `test_a_hung_git_command_fails_with_a_timeout`, `test_a_task_without_a_pull_request_fails_the_delivery`).

### SR-RES-05 A results PR merged or closed is synced back
**Actual behaviour:** `results_pull_request_sync_sensor` launches `sync_results_pull_requests_job` (run key includes the minute, skipped if a run of it is in flight) when any project has results at step PUSHED or OPENED. For PUSHED it looks up the PR by branch and records number, url, step, state DELIVERED. For OPENED it fetches the PR and records MERGED or CLOSED when changed. A PR deleted on the provider (404) is logged and skipped; other provider errors fail the run. `merge_commit_sha` is recorded only when MERGED.
**Evidence:**
- `dagster/app/definitions/sensors/task/pull_request_sync.py:22` `SYNCED`; `:25-31` `get_synced_results`; `:34-79` op; `:88-109` sensor.
- Results are fetched per project and filtered by `?step=` in the webserver (`dagster/app/backend.py:222-226`; `results_api.py:56-62`).
- Each result is synced against its own repository, fetched once per id (`pull_request_sync.py:47-53`).
**Tests:** dagster `test_results_pull_request_sync.py` (`test_a_merged_pull_request_is_recorded`, `test_a_closed_pull_request_is_recorded_without_a_merge_commit`, `test_a_pull_request_still_open_is_left_alone`, `test_a_deleted_pull_request_is_skipped_and_the_others_still_synced`, `test_a_provider_error_other_than_404_fails_the_sync`, `test_a_pushed_result_with_a_pull_request_records_it`, sensor tests); webserver `test_results_and_delivery.py::test_list_filter_by_step`.

### SR-RES-06 Revoked or inactive results link in flight
**Actual behaviour:** Delivery re-checks the link when it runs. If no result exists and the link is inactive, the webserver refuses to create it (409) and delivery logs and skips. If a result exists (UNKNOWN or PUSHED) and the link is not active, delivery records state FAILED, error "results repository access revoked", attempts +1, and returns without raising. Such a result is delivered by a manual relaunch after the link is active. The sync sensor still syncs results of a revoked link, using the result's own repository.
**Evidence:**
- `results_api.py:114-120` 409 for inactive link on new result.
- `dagster/app/delivery/results.py:29` `REVOKED_ERROR`; `:76-83`; `:84-85` a FAILED result goes back to IN_PROGRESS when relaunched.
- `pull_request_sync.py:47-53` (repository read by id, not "current" link).
- `projects_api.py:508-513` unlinking a results repo is refused (400) while results exist; `models/result.py:25-27` FK RESTRICT.
- Revoking needs no drain, so it can happen while tasks are in flight (see SR-LINK-03).
**Tests:** dagster `test_results_delivery.py::test_a_revoked_results_repository_fails_the_delivery_with_the_error_and_raises_nothing`; `test_results_pull_request_sync.py::test_a_revoked_results_repository_is_still_synced`; webserver `test_results_and_delivery.py::test_post_result_refusals`, `test_unlink_and_global_delete_refused_while_results_exist`.

### SR-RES-07 A project with no results link is not handled
**Actual behaviour:** `BackendAPI.get_results_repository` unpacks the list from `GET /projects/<pid>/repositories/results` into exactly one item. With none, the unpack raises `ValueError`, the delivery op fails, and nothing is recorded on a result. A comment in the code states this is not handled. The webserver does not stop a project from having no results link; the list route returns `[]` for it.
**Evidence:**
- `dagster/app/backend.py:185-193` (`(assignment,) = response.json()`, comment at `:189-191`).
- `delivery/results.py:64` called before the try block that records failures.
- `projects_api.py:396-406` list returns the project's links (0 or 1).
**Tests:** none found for the no-link case. `dagster/app/tests/test_backend.py::test_the_results_repository_is_the_assignment_of_the_project` covers the one-link case.

---

## 3.6 Sensors (SR-SENS)

All sensors are created with `default_status=DEFAULT_SENSOR_STATUS`, read once at import from `DAGSTER_SENSORS_INITIAL_STATUS` (default STOPPED) (`dagster/app/config.py:27-34`; chart `templates/dagster-env-config.yaml:21`). Sensor list: `dagster/app/definitions/sensors/git/__init__.py:59-62`, `.../task/__init__.py:111-120`.

### SR-SENS-01 Ingest polls each repository once
**Actual behaviour:** `git_pull_request_ingest_sensor` (every 10 s min) asks the webserver for global trigger repositories with `?active_link=true`, then polls each once with that repository's own secret and the `pr_cursor` the webserver gives it. There is no per-project or per-branch polling; each PR carries its `base_branch` and the webserver matches it per link.
**Evidence:**
- `dagster/app/definitions/sensors/git/pr_ingest.py:19-40`, `:42-61`.
- `dagster/app/backend.py:47-54` `get_pollable_trigger_repositories` (`GET /global/repositories/triggers?active_link=true`).
- `trigger_repositories_api.py:46-61` the filter (repo enabled; any link enabled, not revoked, project enabled).
- `dagster/app/definitions/sensors/git/base.py:40-48` client per repo from its own secret; providers `github`, `gitea`.
- `dagster/app/github.py:34-62` polls closed PRs by `updated` desc, stops at `updated_at <= cursor`; `gitea.py:32-60` filters by `merged_at > cursor`.
- A disabled project does not stop ingest (docstring `pr_ingest.py:15-16`); it gets no evaluation or launch.
**Tests:** dagster `test_pr_ingest_sensor.py::test_only_polls_active_repositories_of_enabled_projects`, `test_posts_one_batch_per_repository_with_new_prs`, `test_queries_the_provider_from_the_global_cursor_without_a_base_branch`; `test_github.py`, `test_gitea.py`, `test_git_api_factory.py`; webserver `test_trigger_repos_active_link_filter`.

### SR-SENS-02 Ingest posts at most 100 PRs per batch, oldest first
**Actual behaviour:** The sensor fetches each merged PR and its files, sorts by (`merged_at`, `number`), and posts in slices of `MAX_BATCH_SIZE = 100`. The webserver also refuses more than 100 (400), and the Dagster client raises `ValueError` over 100. `files_truncated` is set when the provider list reaches 3000 files.
**Evidence:**
- `pr_ingest.py:7` `MAX_BATCH_SIZE`; `:54-61`.
- `trigger_repositories_api.py:108-109`; `dagster/app/backend.py:114-115`.
- `dagster/app/models/pull_request.py:6, 80` (`PROVIDER_FILES_CAP = 3000`).
- Code comment `pr_ingest.py:67-68` and `trigger_repositories_api.py:106-107` flag two open issues (duplicate file path would 500 a batch; one invalid PR refuses the whole batch). Nothing de-duplicates paths.
**Tests:** dagster `test_pr_ingest_sensor.py::test_batches_are_at_most_100_pull_requests_oldest_first`, `test_the_batch_carries_the_facts_and_the_changed_paths`; `test_backend.py::test_batch_creation_is_capped`; webserver `test_pull_requests_and_tasks.py::test_batch_limit`.

### SR-SENS-03 A failing repository does not stop the others
**Actual behaviour:** Each repository is ingested inside try/except; a failure is logged and its URI collected. After the loop, if any failed, the tick raises `RuntimeError` naming them, with the count saved from the others (those PRs are already stored). A batch refused by the webserver fails only that repository.
**Evidence:**
- `pr_ingest.py:26-35`.
**Tests:** dagster `test_pr_ingest_sensor.py::test_a_failing_repository_does_not_stop_the_others_and_fails_the_tick_at_the_end`, `test_a_batch_the_backend_refuses_fails_only_its_repository`.

### SR-SENS-04 Evaluate reads each project's active links; filtering is in the webserver
**Actual behaviour:** `git_pull_request_evaluate_sensor` asks for projects with `enabled=true`, then for each project its trigger links with `?active=true`, then for each link the PR triggers with `?state=UNKNOWN`. All filtering is done by webserver query parameters. A link with an evaluate run in flight (same `project_id` and `repo_id` tags, status NOT_STARTED, QUEUED, STARTING or STARTED) is skipped.
**Evidence:**
- `dagster/app/definitions/sensors/git/pr_evaluate.py:28-36`, `:41-50`.
- `dagster/app/backend.py:33-45` (`get_projects(**filters)` becomes query params), `:56-61` (`active=true`), `:75-107` (`state=` plus pagination, 100 per page).
- Webserver: `projects_api.py:60`; `project_trigger_repositories_api.py:73-74`, `:254-262`.
**Tests:** dagster `test_pr_evaluate_sensor.py::test_only_enabled_projects_and_active_assignments_are_requested`, `test_only_enabled_projects_are_evaluated`, `test_a_repository_with_a_run_in_flight_is_skipped`; `test_backend.py::test_the_state_is_sent_as_a_query_param`, `test_filters_are_sent_as_query_options`.

### SR-SENS-05 Evaluate turns a PR into a task or REJECTED
**Actual behaviour:** The run `evaluate_repository_pull_requests_job` loads the UNKNOWN PR triggers oldest first and maps `evaluate_pull_request` over them (max 3 concurrent; retry 3 times, 5 s exponential). For each it lists the PR's files from git, keeps `.json` files added under `watch_dir`. None: PATCH state REJECTED with cause "No new spec file under ...". More than one: REJECTED naming them. Exactly one: read at the merge commit and POST the raw text to the `/task` route, where the webserver parses it and either creates the task (YIELDED) or rejects the PR. A git or backend failure raises (PR stays UNKNOWN).
**Evidence:**
- `evaluate_job.py:17-29` load op; `:60-73` evaluate op (retry `:62`); `:76-81` job, `MAX_CONCURRENT_EVALUATIONS = 3` (`:14`).
- `pr_parser.py:47-73` `parse`; `:75-82` filter (dir, `.json`, status `added`).
- `evaluate_job.py:32-57` `record_outcome`.
- `pr_evaluate.py:52-58` run key `evaluate/{project}/{repo}/{minute}`.
- Webserver parse and state change: `project_trigger_repositories_api.py:304-351`.
**Tests:** dagster `test_evaluate_job.py::test_a_ready_pr_sends_its_spec_file_and_patches_nothing`, `test_a_pr_without_a_spec_file_is_patched_as_rejected`, `test_a_pr_with_several_spec_files_is_patched_as_rejected`, `test_a_backend_failure_raises_and_leaves_the_pr_untouched`, `test_a_git_failure_raises_and_leaves_the_pr_untouched`, `test_the_job_maps_the_evaluation_over_the_load_and_caps_concurrency`; `test_pr_parser.py`; `test_pr_evaluate_sensor.py::test_the_run_key_includes_the_minute`.

### SR-SENS-06 New 409s are skipped, not errors
**Actual behaviour:** In evaluate, a 409 from the `/task` route (PR no longer UNKNOWN, or link no longer active) is logged as a warning and the PR is skipped. A 400 from that route is logged as an error and not retried (the webserver has already marked the PR REJECTED). Any other status raises. In the run-status sensor, a 409 on the task PATCH (finished task) is skipped with a warning. In delivery, a 409 on creating a result is logged and skipped.
**Evidence:**
- `evaluate_job.py:43-52`.
- `run_status.py:58-63`.
- `delivery/results.py:67-72`.
**Tests:** dagster `test_evaluate_job.py::test_a_409_from_the_task_endpoint_skips_the_pr`, `test_a_400_from_the_task_endpoint_is_left_as_the_backend_rejected_it`; `test_task_run_status_sensor.py::test_a_409_from_a_finished_task_is_skipped`, `test_any_other_backend_error_raises`; `test_results_delivery.py::test_a_refused_result_is_skipped_not_failed`.

### SR-SENS-07 A disabled secret is refused before its token is read
**Actual behaviour:** Every Dagster read of a secret value goes through `read_secret_value`, which raises `PermissionError` if `secret.enabled` is false before calling the store. `GitAPIFactory.for_repository` and delivery's push use it. The launcher checks the dataset's secret `enabled` flag from the API response and fails the task with a cause.
**Evidence:**
- `dagster/app/secrets.py:37-41`; `definitions/sensors/git/base.py:41`; `delivery/results.py:133`.
- `launcher.py:48-55`.
- Dagster's `Secret` model carries `enabled` (`dagster/app/models/secret.py`).
**Tests:** dagster `test_results_delivery.py::test_a_disabled_secret_fails_the_delivery_before_its_token_is_read`; `test_task_launcher.py::test_a_task_whose_dataset_secret_is_disabled_is_failed_with_the_cause`. `test_secrets.py` and `test_git_api_factory.py` have no disabled-secret test.

### SR-SENS-08 Launcher starts runs for PENDING tasks of enabled projects
**Actual behaviour:** `task_launcher_sensor` asks for projects with `enabled=true`, then each project's tasks with `status=PENDING`, and yields a `RunRequest` for `k8s_pipes_job` per task with run key `task/<id>/<attempt>` and tags (`trigger=task`, `task_id`, `attempt`, `project_id`, `project`). If the task names a dataset it reads the project's link to it; if the link is not active, or the dataset secret is disabled, it PATCHes the task to FAILED with `state_cause` and does not launch. It does not move the task to QUEUED itself.
**Evidence:**
- `launcher.py:16-34`, `:36-67`; patch to FAILED `:52-54`.
- `dagster/app/backend.py:153-165` (`GET /projects/<id>/tasks?status=PENDING`, paginated).
- `dagster/app/definitions/sensors/task/__init__.py:21-36` sensor, 10 s interval.
- `build_run_config(task.spec, dataset)`: `dagster/app/definitions/run_config.py`.
**Tests:** dagster `test_task_launcher.py` (`test_launches_a_pending_task`, `test_only_enabled_projects_are_acted_on`, `test_a_task_whose_dataset_is_not_active_is_not_launched`, `test_other_tasks_are_launched_when_one_dataset_is_not_active`, `test_every_pending_task_of_every_page_is_launched`, `test_the_launcher_patches_nothing_and_re_yields_the_same_run_key`); `test_run_config.py`.

### SR-SENS-09 Only run-status sensors write task status
**Actual behaviour:** Five run-status sensors (QUEUED, STARTED, SUCCESS, FAILURE, CANCELED) monitor `k8s_pipes_job` and PATCH the task: status map QUEUED to QUEUED, STARTED to RUNNING, SUCCESS to SUCCESS, FAILURE to FAILED, CANCELED to CANCELED; they record `executor_run_id`, `started_at` on start, `completed_at` on terminal runs. They act only on runs tagged `trigger=task`. Delivery runs are tagged `trigger=delivery`, so they never touch a task. One exception: the launcher PATCHes FAILED (with `state_cause`) when a dataset is not usable (see SR-SENS-08). The webserver also changes status on retry (PENDING).
**Evidence:**
- `.../task/__init__.py:39-108` sensors; `:41-42` tag check.
- `run_status.py:17-25` map; `:31-64`.
- `delivery.py:28-36` docstring and tags; `delivery/results.py` docstring: "Delivery never touches the task's own status".
- `launcher.py:52-54`; `tasks_api.py:202` retry.
**Tests:** dagster `test_task_run_status_sensor.py::test_the_run_status_maps_to_the_task_status`, `test_the_map_covers_exactly_the_statuses_the_sensors_monitor`, `test_registered_sensor_ignores_runs_of_other_triggers`; `test_results_delivery.py::test_the_sensor_ignores_runs_that_are_not_task_runs`. The launcher's FAILED write is covered by `test_task_launcher.py::test_a_task_whose_dataset_secret_is_disabled_is_failed_with_the_cause`.

### SR-SENS-10 Dagster never fetches lists to filter them in Python
**Actual behaviour:** The sensors pass filters as query parameters: projects `enabled`, links `active`, PRs `state`, tasks `status`, results `step`, repos `active_link`. Paging helpers walk all pages. Exceptions that remain Dagster-side: the evaluate job sorts UNKNOWN PRs by `merged_at`; the ingest sensor sorts fetched PRs; the sync sensor fetches all projects (no filter) then asks per project for results by step; `get_datasets` unwraps a page or a bare list.
**Evidence:**
- `dagster/app/backend.py:33-61, 75-107, 153-165, 222-226`.
- `pr_evaluate.py:28-33`; `launcher.py:25-26`; `pull_request_sync.py:25-31`.
- `evaluate_job.py:28`; `pr_ingest.py:54-56`.
**Tests:** dagster `test_backend.py::test_filters_are_sent_as_query_options`, `test_get_tasks_filters_by_status_and_project`, `test_list_by_step`, `test_get_active_repositories`; `test_results_pull_request_sync.py::test_the_results_are_requested_by_step_of_each_project`.

---

## 3.7 Healthchecks (SR-HC)

### SR-HC-01 Global and per-resource healthchecks
**Actual behaviour:** Read-only GET routes return 200 even when a check fails; the failure is in the body (`status`, `health_check.message`, `status_code`, `latency_ms`). `GET /global/healthcheck` checks every dataset, secret, trigger repo and results repo in parallel (8 threads) and returns `status` ok only if all are OK, with the four lists. Per resource: dataset (can the node connect to its DB with its secret), secret (is it in the store with the keys its users need: `Dataset.SECRET_KEYS` if used by datasets, `TOKEN` if used by repos), repositories (HTTP GET to the provider repo API with bearer token; OK, UNAUTHORIZED, NOT_FOUND, ERROR, UNREACHABLE, SECRET_MISSING). Values are never returned. Disabled resources are still checked and show `enabled`.
**Evidence:**
- `healthcheck_api.py:157-182` global; `:185-226` per resource routes (`/global/datasets/<id>/healthcheck`, `/global/secrets/<label>/healthcheck`, `/global/repositories/triggers/<id>/healthcheck`, `/global/repositories/results/<id>/healthcheck`).
- `:47` `HEALTHCHECK_MAX_WORKERS = 8`; `:56-58` thread pool; DB/cluster reads happen in the request, only network calls in threads (`:65-118`).
- `models/git_repository.py:80-135` `prepare_connection_check` / `_request_check` / `_status_of` (401, 403 unauthorized; 404 not found); 5 s timeout (`:19`).
- `:93-118` secret check expected keys; `dtos/healthcheck.py:28-39`.
- Auth `can_admin_dataset` and `@audit` on all of them.
**Tests:** `test_healthchecks_all.py`: `test_global_healthcheck_empty_is_ok`, `test_global_healthcheck_shapes_and_per_resource_ok`, `test_global_aggregate_error_when_any_resource_fails`, `test_every_failure_status_is_reported_verbatim`, `test_disabled_resource_is_still_checked_and_flagged`, `test_secret_missing_keys_depend_on_its_users`, `test_repository_http_status_and_exceptions_map_to_status`, `test_dataset_connection_failures_are_reported_not_500`.

### SR-HC-02 Project and link healthchecks
**Actual behaviour:** `GET /projects/<pid>/healthcheck` checks each trigger link's repository and the project's results link, and returns the project with `status`, `trigger_repositories` (with `pr_count`) and `results_repository`. Status is "error" if there are no trigger links, or any check is not OK. Per-link routes (`/projects/<pid>/datasets/<id>/healthcheck`, `.../secrets/<label>/healthcheck`, `.../repositories/triggers/<id>/healthcheck`, `.../repositories/results/<id>/healthcheck`) return the global resource's check plus the link's `enabled`, `revoked`, `active` (and `pr_count` or `target_dir`); 404 if the project has no such link.
**Evidence:**
- `healthcheck_api.py:229-279` project; `:270` `healthy = repositories and _is_ok(...)` (empty trigger list is not healthy); `:282-324` link routes (use the link finders from the link APIs, so 404 shape is the same).
- `:121-154` link health builders; `dtos/healthcheck.py:42-74`.
**Tests:** `test_healthchecks_all.py::test_project_healthcheck_ok_shape`, `test_project_without_trigger_link_is_error`, `test_project_aggregate_error_when_a_link_fails`, `test_link_healthcheck_shapes_and_flags`, `test_link_healthchecks_404`, `test_network_exception_is_in_global_and_project_aggregate`.

---

## 3.8 API conventions (SR-API)

### SR-API-01 Admin routes live under /global, unchanged
**Actual behaviour:** Users and registries are under `/global/users` and `/global/registries`. A test asserts no route starts with `/users`, `/registries` or `/whitelisted_images`. The whitelisted images blueprint exists (prefix `/global/whitelisted_images`) but is not registered. `GET /audit` and `PATCH /delivery-secret` (501) are still at the root, not under `/global`. The DAR blueprint (`/requests`) exists but is not registered. Dagster sensor admin routes are under `/dagster`.
**Evidence:**
- `users_api.py:16`; `registries_api.py:19`; `whitelisted_images_api.py:27`; registration `webserver/app/__init__.py:84-87` (whitelisted images commented out; `dar_api` not imported).
- `admin_api.py:20, 25, 35` (prefix `/`).
- `dagster_api.py:17`, routes `:53-98` (admin only via `before_request`).
**Tests:** `test_smoke.py::test_admin_routes_live_under_global`, `test_reset_password_needs_no_token`; `keycloak/test_keycloak_users.py`. None found for `/audit` path or `/dagster/sensors`.

### SR-API-02 Consistent errors, pagination and filters
**Actual behaviour:** Errors are `{"error": "<message>"}` with the HTTP code; extra data goes in `details` (e.g. the in-flight task ids on a 409). Statuses used: 400 invalid, 401/403 auth, 404 not found, 409 conflict, 501 not implemented, 502 Dagster unreachable. A DB integrity error is 409 "Record already exists". Any other exception is 500 "Internal Error". Every JSON body must be an object (400 otherwise). Pagination is not uniform: `page_of` (`items`, `page`, `per_page`, `total`, `pages`) for projects, datasets, registries, audit and the global PR list; tasks use the key `tasks`; link lists and global repo/secret lists are bare arrays; project PR list uses `items`. `/projects` and `/audit` use `parse_query_params` (field=value and `__ne/__eq/__lt/__gt/__lte/__gte`, `per_page` default 25, no clamp). Task and global PR lists clamp `page`/`per_page` to at least 1. Non-integer page values are 400.
**Evidence:**
- `webserver/app/__init__.py:45-51` handler (`error`, `details`); `:55-59`; `:61-66`; `:68-72` JSON object check.
- `helpers/exceptions.py:8-70` classes and codes (`DagsterError` 502).
- `dtos/base.py:31-38` `page_of`; `helpers/query_filters.py:18-27, 30-81`.
- `tasks_api.py:94-116`; `project_trigger_repositories_api.py:236-273`; `trigger_repositories_api.py:82-87`.
- Lists as bare arrays: `secrets_api.py:126`, `trigger_repositories_api.py:61`, `results_repositories_api.py:43`, `projects_api.py:195,297,406`.
**Tests:** `test_pagination_and_filters.py` (`test_page_past_the_end_is_empty_200`, `test_page_or_per_page_below_one_is_clamped`, `test_non_numeric_page_params_are_400`, `test_projects_default_shape_and_walk`, `test_tasks_pages_and_ordering`, `test_global_repo_lists_are_ordered_arrays`); `test_global_resources.py::test_methods_bodies_and_empty_lists`; `test_dtos.py::TestPageOf`.

### SR-API-03 The API exposes the real model; no flat compatibility layer
**Actual behaviour:** DTOs mirror the tables: a link DTO nests the global resource (`dataset`, `secret`, `trigger_repository`, `results_repository`) next to `enabled`, `revoked`, `active`. Trigger and results repos are top-level only under `/global`. There are no old flat routes (`/datasets`, `/repositories`, `/tasks`, `/secrets`) in the app. A PR trigger is shown with the PR facts joined in. Trigger repo DTO carries a nested `secret` (reference only) and `pr_cursor`.
**Evidence:**
- `dtos/dataset.py:51-67`, `dtos/secret.py:19-35`, `dtos/trigger_repository.py:13-69`, `dtos/results_repository.py`.
- Route prefixes: see SR-GLOB-01 and SR-API-01; `test_smoke.py::test_admin_routes_live_under_global`.
- Error text on removed shapes points to the new route (e.g. `trigger_repositories_api.py:148-151`).
**Tests:** `test_dtos.py`; `test_smoke.py`; `test_live_client_integration.py::test_fncli_setup_models_parse`. (The old `test_contract_fixtures.py` no longer exists.)

---

## 3.9 Dev tooling and tests (SR-DEV)

### SR-DEV-01 Dagster tests run in Docker
**Actual behaviour:** `make tests_dagster` runs `cd dagster && ./run_tests.sh ci`. The script builds the Dagster image (`docker compose -f docker-compose-tests-ci.yaml build base`), then runs `pytest -v .` in compose service `app` (image `dagster_app_test`, built `FROM dagster_fn_base` by `build/test.Dockerfile`, which installs `.[dev,cli]`). Each run has its own compose project name and is torn down on exit. Non-ci mode adds `-x` and bind-mounts `./app`, `./fncli` and `pyproject.toml`. One run covers Dagster and fncli: 470 passed (346 + 124), per the owner (not re-run here). CI calls `make tests_dagster` (`.github/workflows/build.yml:184`).
**Evidence:**
- `Makefile:19-20`; `dagster/run_tests.sh:1-28`; `dagster/docker-compose-tests-ci.yaml`, `docker-compose-tests.yaml`; `dagster/build/test.Dockerfile`.
- `dagster/pyproject.toml` `testpaths = ["app/tests", "fncli/tests"]`.
- `make pylint_dagster` (`Makefile:16-17`).
**Tests:** n/a (this is the runner). `dagster/app/tests/test_*.py` (23 files) and `dagster/fncli/tests/test_*.py` (8 files).

### SR-DEV-02 Webserver tests
**Actual behaviour:** `webserver/run_tests.sh` runs pytest in docker compose with a Postgres 17 container (`db`), with its own compose project name. The Flask app uses the real database; Keycloak and the Kubernetes client are mocked in `conftest.py`. A session fixture exits the run if the DB is unreachable. Targeted runs: `./run_tests.sh [ci] <pytest args>`. Integration scripts for Keycloak/chart live in `webserver/integration_tests` and run separately (`run_integration_tests.sh`).
**Evidence:**
- `webserver/run_tests.sh`; `webserver/docker-compose-tests-ci.yaml:3-17`; `webserver/Makefile` (`tests_local`, `tests_ci`).
- `webserver/tests/conftest.py:36-55` DB check; `:111, 162-177, 536, 609-654` mocks.
- Test layout: `webserver/tests/*.py`, `tasks/`, `keycloak/`; `webserver/tests/TEST_PLAN.md`.
**Tests:** n/a. Main shared-resources files: `test_global_resources.py`, `test_trigger_repositories_and_links.py`, `test_projects_api.py`, `test_pull_requests_and_tasks.py`, `test_results_and_delivery.py`, `test_healthchecks_all.py`, `test_pagination_and_filters.py`, `test_triggers.py`, `test_e2e_flow.py`, `test_live_client_integration.py` (runs fncli and dagster client code against the real routes).

### SR-DEV-03 fncli lives in dagster/fncli and shares app.* code
**Actual behaviour:** Done. fncli is the second package of `dagster/pyproject.toml` (`fncli = "fncli.cli:cli"`, `cli` extra = click, python-dotenv, `include = ["app*", "fncli*"]`). It imports `app.*` (`app.backend.BackendAPI`, `app.models`, `app.gitea`, `app.utils`, `app.config`, `app.git_uri`). There is no `scripts/fncli` and no `dagster/fncli/dagster/` copy directory. `FncliBackendAPI` (`dagster/fncli/backend.py`, 240 lines) subclasses `app.backend.BackendAPI` and adds only the setup/teardown calls. Install from the repo root: `pipx install --force --editable './dagster[cli]'` (`dagster/fncli/README.md:56`). The Dagster Docker image also contains `fncli/` (`.dockerignore` allows `fncli/**`).
**Evidence:**
- `dagster/pyproject.toml` (scripts, extras, packages, testpaths).
- Imports: `fncli/backend.py:1-6`, `gitea.py:5-6`, `sensors.py:3`, `cmds/common.py:13,16`, `cmds/*.py`.
- `ls scripts/fncli` fails. `grep -rn scripts/fncli` finds hits only in `project/moonshot-*`.
- Commands: `fncli/cli.py:13` (modules: actions, dataset, hello_world, pr, project, repository, secret, sensor, state, verify; each exports `COMMANDS`).
- Commits `ed10916f` (move), `5c0c0cbe` (copies deleted), `95d61117` (tests fixed).
**Tests:** `dagster/fncli/tests/` (`test_backend.py`, `test_cli.py`, `test_config.py`, `test_dataset.py`, `test_git_uri.py`, `test_pr.py`, `test_sensor.py`, `test_verify.py`; 124 tests). `webserver/tests/test_live_client_integration.py` runs the fncli backend client (`fncli.backend`) and the Dagster client against the real routes; it skips if `dagster/fncli` is missing. The old `test_contract_fixtures.py` and contract-fixture folders are gone.

### SR-DEV-04 Schema: baseline migration edited in place
**Actual behaviour:** `webserver/migrations/versions/` holds one migration, `001_baseline.py` (`down_revision = None`) that creates all tables including the shared-resources ones (`secrets`, `project_secrets`, `trigger_repositories`, `project_trigger_repositories`, `results_repositories`, `project_results_repositories`, `pull_requests`, `pull_request_files`, `triggers`, `pull_request_triggers`, `api_request_triggers`, `task_specs`, `tasks`, `results`, `pull_request_results`). Git history shows 17 commits touching that file, i.e. it has been edited rather than followed by new revisions.
**Evidence:**
- `webserver/migrations/versions/001_baseline.py:13-14` revisions; table creation `:21-408`.
- `git log --oneline -- webserver/migrations/versions/001_baseline.py | wc -l` gives 17.
- `webserver/generate_migration.py` and `webserver/alembic.ini` exist.
**Tests:** none found for the migration itself (webserver tests use the app's models against Postgres).

### SR-DEV-05 Dev cluster ownership guard
**Actual behaviour:** `scripts/deploy_owner.sh claim|show|release` keeps a ConfigMap `fn-dev-owner` in namespace `default` (worktree path, branch, sha, time, user). `claim` fails (exit 1) if another worktree owns it, unless `FORCE_OWNER=1`. `deploy.sh` and `upgrade.sh` call `claim` first. `teardown.sh` calls `release` at its end (no owner check). `make deploy-owner` runs `show`.
**Evidence:**
- `scripts/deploy_owner.sh:9-10, 16-31` (claim and check at `:20`), `:32-42` show, `:43-45` release.
- `scripts/deploy.sh:10`; `scripts/upgrade.sh:12`; `scripts/teardown.sh:230`; `Makefile:86-87`.
**Tests:** none found.

### SR-DEV-06 End-to-end script
**Actual behaviour:** `scripts/e2e_shared_resources.sh` runs against a live kind cluster (context `kind-fn`) with Tilt port-forwards (backend :5000, Gitea :4000, Dagster :3000). It: runs `fncli setup-project`, `project-healthcheck`, `start-sensor --sensor all`, opens and merges three Gitea PRs (watched, unwatched, invalid), waits for PRs to be evaluated (`scripts/e2e_check.py wait-prs`), waits for the task to reach SUCCESS (`wait-tasks`, skippable with `SKIP_TASKS=1`), prints a snapshot, and tears down unless `KEEP=1`. The script header says it was not run in the session that wrote it.
**Evidence:**
- `scripts/e2e_shared_resources.sh:1-75`; `scripts/e2e_check.py`.
**Tests:** `webserver/tests/test_live_client_integration.py::test_e2e_check_script_reads_the_real_routes`; `webserver/tests/test_e2e_flow.py::test_full_flow`.

---

---

# Part 2: gitea-mirror (GM)

Short map: one Flask app (`app/__init__.py:13-33`) with blueprints `main` (`/health`), `mirrors` (`/mirrors`), `webhooks` (`/webhooks`). Entry point `python -m app.runner` (waitress on port 5000 plus a timer thread). Five tables: `mirrors`, `mirror_state`, `mirrored_pull_requests`, `webhooks`, `webhook_deliveries`.

## GM-01 The mirror is self-contained

**Actual behaviour:** The service lives wholly in `gitea-mirror/`. It has its own Dockerfile, requirements, Alembic migrations, and Postgres database. Its `app/` code imports only itself and third-party libraries. Nothing in `webserver/` or `dagster/` references it.

**Evidence:**
- `gitea-mirror/Dockerfile:1-32` builds a standalone image (python 3.13, git installed, entrypoint `app.runner`).
- `gitea-mirror/requirements.txt` is its own dependency list. `gitea-mirror/alembic.ini` and `migrations/versions/001_baseline.py` are its own migrations.
- Import scan of `app/` found only `app.*`, stdlib, flask, sqlalchemy, requests, waitress and alembic.
- DB env vars are `GITEA_MIRROR_DB_*` (`app/helpers/const.py:14-19`).
- Grep of the repo outside `gitea-mirror/` finds the name only in docs, `k8s/`, `.github/workflows/build.yml` and `scripts/fncli/`.

**Tests:** `tests/test_health.py::test_migration_creates_tables`, `tests/test_delivery_outbox.py::test_model_and_migration_have_no_drift`. Nothing tests "self-contained" directly.

---

## GM-02 Outbound only, GitHub.com upstream only

**Actual behaviour:** The service pulls from GitHub and pushes to Gitea. It never accepts inbound GitHub webhooks. Upstream must be exactly `https://github.com/<owner>/<repo>`, checked on the API and again at sync. The GitHub token is sent only to `api.github.com` and to git URLs under `https://github.com/`.

**Evidence:**
- `app/helpers/validation.py:9-12` `UPSTREAM_RE` is a fullmatch on `https://github.com/{name}/{name}`. It is enforced at create and patch (`validation.py:47`).
- `app/sync.py:104-116` `check_upstream` rejects non-https, other hosts, ports and userinfo, with `UnsupportedUpstream`. It is called first in `_replay` (`sync.py:204`).
- `app/sync.py:119-143` `run_git` sets `http.<scope>.extraHeader` and `http.followRedirects=false` through `GIT_CONFIG_*` env. The scope is `https://github.com/` (`sync.py:37`, used at `sync.py:236`).
- `app/github.py:12` `GH_API_BASE_URL = https://api.github.com`.
- There is no route that receives GitHub events. The only routes are listed under GM-13.
- `k8s/.../gitea-mirror-networkpolicy.yaml:151-157`: egress to `0.0.0.0/0` on TCP 443.

**Tests:** `tests/test_validation.py::test_upstream_uri_rejected`, `::test_upstream_uri_accepted`, `::test_patch_upstream_uri_rejected`. `tests/test_sync_safety.py::test_sync_refuses_non_github_upstream`, `::test_github_header_is_scoped_to_github_and_not_in_argv`, `::test_header_not_sent_to_other_host_for_real`.

---

## GM-03 Merged PRs become Gitea PRs marked manually-merged

**Actual behaviour:** For each merged GitHub PR, the service opens a Gitea PR from branch `pr/<n>` to the base branch. It opens the PR as the author's shadow user and fast-forwards the base to the merge commit. It then calls the Gitea merge endpoint with `Do: manually-merged` and the merge commit sha. The Gitea repo is a normal private repo (not a Gitea pull mirror) with `allow_manual_merge` on.

**Evidence:**
- `app/sync.py:276-278` `gitea.open_pull_request(org, repo, login, title, "Mirrored from {upstream}/pull/{n}", head, base)`. Head is `pr/{n}`.
- `app/sync.py:279` pushes `{sha}:refs/heads/{base}`.
- `app/sync.py:280-281` `gitea.mark_manually_merged(...)`, unless an existing Gitea PR is already merged.
- `app/gitea.py:196-204` `POST /repos/{org}/{repo}/pulls` with a `Sudo` header. `app/gitea.py:206-215` `POST .../pulls/{index}/merge` with `{'Do': 'manually-merged', 'MergeCommitID': sha}`. A 400 starting "commit not found in base" becomes `MergeCommitNotInBaseError`.
- `app/gitea.py:130-140` `ensure_repo`: `POST /orgs/{org}/repos` with `private: True, auto_init: False`, then `PATCH` with `allow_manual_merge: True`. `ensure_org` makes a private org (`gitea.py:123-128`).
- `app/sync.py:233-248` fetches `refs/heads/*` plus `refs/pull/<n>/head` from GitHub. It force-pushes branches as-is and each PR head as `refs/heads/pr/<n>`.
- `app/sync.py:250` `set_default_branch`. `app/sync.py:314` restores the base to the upstream tip at the end.
- Only merged PRs are kept: `app/github.py:171` `if pr['merged_at']`. The listing is `state=closed`, `base=<base_branch>` (`github.py:162`).

**Tests:** `tests/test_sync_gitea.py::test_sync_replays_each_merge_style_and_second_run_is_noop` (merge commit, squash and fast-forward; checks `merged`, `merge_commit_sha`, head, base, author, files). It needs a real Gitea (`pytestmark skipif GITEA_MIRROR_GITEA_URL`). `tests/test_sync_gitea.py::test_first_sync_leaves_default_branch_at_base`. `tests/test_gitea_client.py::test_ensure_repo_normal_private_manual_merge_idempotent`, `::test_open_pull_request_as_user`, `::test_mark_manually_merged`, `::test_mark_manually_merged_commit_not_in_base` (real Gitea).

---

## GM-04 PRs are replayed in merged order, with the base rewound

**Actual behaviour:** New PRs are sorted by `merged_at`, oldest first. Before opening each PR, the Gitea base branch is force-pushed to `<merge_commit_sha>^1`, so the PR diff is non-empty. After opening, the base is moved to the merge commit. When all PRs are done, or on any error, the base is restored to the upstream tip.

**Evidence:**
- `app/sync.py:224` `new = sorted(..., key=merged_at)`.
- `app/sync.py:260` `push(f'{sha}^1:refs/heads/{base}')`. If that push fails, the PR is quarantined as `PoisonPullRequest` (`sync.py:261-262`).
- `app/sync.py:279` push `{sha}:refs/heads/{base}`.
- `app/sync.py:293-294, 308-314` `restore_base()` pushes the cache's `refs/heads/{base}` (the fetched upstream tip). It runs on `BaseException` and after the loop.
- `app/sync.py:268-275`: if a Gitea PR for `pr/<n>` already exists and is not merged, the code waits for Gitea to recompute the base (`gitea.py:181-194`).
- All pushes use `--force` (`sync.py:244`).
- A PR with no valid 40-hex merge sha is quarantined (`sync.py:256-257`).

**Tests:** `tests/test_sync_gitea.py::test_sync_replays_each_merge_style_and_second_run_is_noop` (asserts `mirrored == [1, 2, 3]` in merged order, although `updated_at` order is 1, 3, 2). `tests/test_sync_robust_gitea.py::test_failure_mid_replay_restores_base_to_tip`, `::test_transient_failure_after_open_does_not_duplicate_pr`, `::test_poison_prs_are_quarantined_and_do_not_block_later_prs` (all real Gitea).

---

## GM-05 Both PR numbers are stored and sent

**Actual behaviour:** Each mirrored PR row stores the GitHub number (`number`) and the Gitea index (`gitea_pr_number`). The webhook event sends both as `number` and `gitea_pr_number`.

**Evidence:**
- `app/models/mirror.py:36-51`: columns `number`, `gitea_pr_number`, `merge_commit_sha`, `merged_at`, `author`, `title`. Unique on `(mirror_id, number)`.
- `app/sync.py:283-286` creates the row with both numbers.
- `app/delivery.py:303-304` event keys `number` and `gitea_pr_number`.
- `schema/pull_request.mirrored.json:9, 26-27` requires both.

**Tests:** `tests/test_webhooks.py::test_delivery_signed_and_schema_valid`, `::test_schema_rejects_bad_events`. `tests/test_sync_gitea.py::test_sync_replays_each_merge_style_and_second_run_is_noop` checks `gitea_pr_number` rows.

---

## GM-06 Sync starts from now; no history backfill

**Actual behaviour:** Creating a mirror writes a `mirror_state` row with `cursor = now`. A merged PR whose `merged_at` is before the cursor and which is not already mirrored is classed as history. It is not replayed. The cursor never moves past the `merged_at` of a PR still pending.

**Evidence:**
- `app/mirrors.py:72` `MirrorState(mirror_id=..., cursor=datetime.now(timezone.utc))`. The column is NOT NULL with default `now()` (`models/mirror.py:30`).
- `app/sync.py:208-210` also sets the cursor to now if it is None. The column forbids that, so the branch looks unreachable.
- `app/sync.py:221-222` `history = {number for p in pulls if not mirrored and merged_at < start}`.
- `app/sync.py:172-189` `advance_cursor`: moves to the latest `updated_at` such that every listed PR at or before it is settled. It is then capped at `min(merged_at)` of pending PRs (`sync.py:185-187`).
- `app/github.py:152-181` `list_merged_pulls`: lists closed PRs sorted by `updated desc`, stops at the first PR with `updated_at < cursor`, and returns oldest first. A PR updated exactly at the cursor is still listed.

**Tests:** `tests/test_sync_robust_gitea.py::test_pr_merged_before_mirror_creation_but_updated_later_is_not_replayed`, `::test_pending_pr_merged_earlier_than_done_ones_is_not_mistaken_for_history` (real Gitea). `tests/test_sync.py::test_advance_cursor_stops_at_first_unmirrored_by_updated_at`. `tests/test_sync_safety.py::test_advance_cursor_never_passes_merged_at_of_a_pending_pr`. `tests/test_github_client.py::test_merged_pulls_paginate_and_stop_at_cursor`, `::test_cursor_stop_skips_later_pages`, `::test_pr_updated_exactly_at_cursor_is_still_listed`. `tests/test_delivery_outbox.py::test_cursor_not_null`.

---

## GM-07 Authors are shadow Gitea users

**Actual behaviour:** Each GitHub author maps to a Gitea user named `gh-<login>`. Logins with odd characters get a short hash suffix. The user has email `<name>@shadow.invalid`, a random password, and private visibility. An existing Gitea account with that name but no `@shadow.invalid` email raises an error and is never adopted. Sudo is refused for any name not starting `gh-`. The shadow user is added as a collaborator with write access before opening the PR. `POST /mirrors/:id/users/sync` pre-creates users for contributors and collaborators. Mirror creation also tries this.

**Evidence:**
- `app/gitea.py:14-39` `shadow_login`: prefix `gh-`, max length 40. Unclean logins become `gh-<stem>.<sha256[:8]>`.
- `app/gitea.py:100-121` `ensure_user`: `GET /users/{login}`, then `POST /admin/users` with `email {login}@shadow.invalid`, `must_change_password False`, `visibility private`.
- `app/gitea.py:78-84` Sudo guard (`ValueError` unless the name starts with `gh-`).
- `app/gitea.py:156-160` `PUT /repos/{org}/{repo}/collaborators/{login}` with `permission: write`. It is called at `sync.py:263-264`.
- `app/users.py:5-10` `sync_users`. `app/github.py:136-150` `list_users` reads `/contributors` plus `/collaborators`; a 403 on collaborators is ignored.
- `app/mirrors.py:76-82` runs the preload at create. Failure is recorded in the response as `users_sync` and the mirror stays. `app/mirrors.py:150-159` `POST /mirrors/<id>/users/sync` returns 200, 501 (`NotImplementedError`) or 502 (`UserSyncError`).
- `app/clients.py:24-31` still holds "Unconfigured" client stubs that raise `NotImplementedError`. The app uses real clients (`__init__.py:18-19`).

**Tests:** `tests/test_sync_safety.py::test_shadow_logins_are_prefixed_and_distinct`, `::test_shadow_login_of_empty_result_is_valid`, `::test_shadow_login_distinct_for_symbol_only_logins`, `::test_shadow_login_length_limited`, `::test_sudo_as_non_shadow_user_is_refused`. `tests/test_sync.py::test_shadow_login`, `::test_shadow_login_of_bot_keeps_readable_stem`. `tests/test_sync_robust_gitea.py::test_shadow_user_never_aliases_a_real_account`, `::test_existing_non_shadow_account_with_shadow_name_is_refused`, `::test_org_named_like_shadow_user_is_refused`, `::test_bot_and_hyphen_logins_become_distinct_users`, `::test_login_that_sanitises_to_empty_gets_a_valid_user`, `::test_pr_by_admin_named_author_is_opened_as_shadow`. `tests/test_gitea_client.py::test_ensure_user_*`, `::test_add_collaborator`. `tests/test_github_client.py::test_list_users_merges_contributors_and_collaborators`, `::test_list_users_without_push_access_uses_contributors`. `tests/test_mirrors.py::test_users_sync*`, `::test_create_users_sync_*`.

---

## GM-08 A PR is recorded before the cursor advances; repeats are harmless

**Actual behaviour:** After the Gitea steps for one PR, the code inserts the `mirrored_pull_requests` row, its webhook delivery rows, and the cursor update in a single commit. Already-mirrored numbers are filtered out before replay. The DB also has a unique key on `(mirror_id, number)`. Before opening a Gitea PR, the code looks for an existing one with head `pr/<n>` and finishes that one instead of opening a duplicate. A transient Gitea 5xx stops the run for retry next round. A poison PR (no merge sha, unreachable parent, Gitea 4xx) is quarantined, its transaction is rolled back, and later PRs continue. At the end the run raises `PullRequestsFailed`, and `last_error` records the failed PRs. One advisory lock per mirror stops concurrent syncs.

**Evidence:**
- `app/sync.py:283-291` row, `enqueue_deliveries`, `advance_cursor`, then one `db.session.commit()`.
- `app/sync.py:213-223` filters `mirrored_numbers` already in the table.
- `app/models/mirror.py:50` `UniqueConstraint('mirror_id', 'number')`.
- `app/sync.py:268-281` `find_pull_request` first (`gitea.py:162-176`, lists `state=all` and matches `head.ref`). If the PR is already merged, `mark_manually_merged` is skipped.
- `app/sync.py:302-307` quarantine. `sync.py:303-304` re-raises on `GiteaError.status >= 500`.
- `app/sync.py:315-316` `PullRequestsFailed`.
- `app/sync.py:339-349` `resync` takes `pg_try_advisory_lock(20020, mirror_id)` on its own connection and raises `MirrorBusy` if held.
- `app/sync.py:320-336` `_sync_recording` writes `last_sync_at`, `last_success_at` and `last_error` (scrubbed, max 4096 chars).

**Tests:** `tests/test_sync_gitea.py::test_sync_replays_each_merge_style_and_second_run_is_noop` (second run is a no-op, and a cursor reset still mirrors nothing). `tests/test_sync_robust_gitea.py::test_transient_failure_after_open_does_not_duplicate_pr`, `::test_poison_prs_are_quarantined_and_do_not_block_later_prs`. `tests/test_sync.py::test_resync_busy_when_locked`.

---

## GM-09 Webhooks are generic subscriptions

**Actual behaviour:** A webhook is a row with `url`, `secret_namespace`, `secret_key` (a reference to a k8s secret holding the HMAC key), optional `mirror_id`, and `enabled`. With `mirror_id` null it receives events for all mirrors. With a `mirror_id` it receives only that mirror's events. Deleting a mirror cascades to its scoped webhooks. The API is CRUD plus a test ping and a delivery listing.

**Evidence:**
- `app/models/mirror.py:54-62` `Webhook` model.
- `app/webhooks.py:162-238`:
  - `GET /webhooks` returns 200.
  - `POST /webhooks` returns 201.
  - `GET`, `PATCH` and `DELETE /webhooks/<id>` return 200, 200 and 204.
  - `POST /webhooks/<id>/test` returns 200 `{status: ok}` or 502 `{status: failed, reason: <class name>}`.
  - `GET /webhooks/<id>/deliveries[?status=]` returns the last 100, newest first (`webhooks.py:241-249`).
- Required fields are `url`, `secret_namespace`, `secret_key` (`webhooks.py:24`). `mirror_id` must be an int or null and must exist (`webhooks.py:124-129`).
- Create and patch check that the secret is readable and non-empty (`webhooks.py:96-103`, `171`, `189-193`). A failure returns 400.
- `app/delivery.py:344-349` `enqueue_deliveries` matches `enabled` and `(mirror_id IS NULL OR mirror_id = pr.mirror_id)`.
- Only one event type is sent for PRs, `pull_request.mirrored`, plus `ping` (`delivery.py:264-265`).
- `models/mirror.py:61`: FK `mirror_id` with `ondelete CASCADE`.

**Tests:** `tests/test_webhooks.py::test_create_defaults_and_serializes`, `::test_create_validation_400`, `::test_create_missing_fields_400`, `::test_404s`, `::test_patch_and_delete`, `::test_deleting_mirror_cascades_scoped_webhook`, `::test_enqueue_matches_enabled_and_scope`, `::test_deliveries_listing_newest_first`, `::test_test_ping_signed`, `::test_test_ping_receiver_failure_502`, `::test_webhook_secret_*`, `::test_patch_secret_ref_is_revalidated_and_unrelated_patch_is_not`.

---

## GM-10 Event body and signature

**Actual behaviour:** The event is compact JSON. The body is signed with HMAC-SHA256 using the key read from the webhook's secret field `token`. The signature header is `sha256=<hex>`. Extra headers carry delivery id, event name and a send-time timestamp. The timestamp is not part of the signature.

**Evidence:**
- `app/delivery.py:294-309` `build_event`: keys `event`, `delivery_id`, `mirror{upstream_uri, gitea_owner, gitea_repo}`, `number`, `gitea_pr_number`, `title`, `author`, `merged_at` (isoformat), `merge_commit_sha`.
- `app/delivery.py:290-291` `sign` returns `'sha256=' + hmac(key, body, sha256).hexdigest()`.
- `app/delivery.py:315` body is `json.dumps(event, separators=(',', ':'))`.
- Headers (`delivery.py:266-273, 319-325`): `X-Gitea-Mirror-Signature`, `X-Gitea-Mirror-Delivery`, `X-Gitea-Mirror-Event`, `X-Gitea-Mirror-Timestamp` (unix seconds), `Content-Type: application/json`.
- `delivery_id` is `WebhookDelivery.delivery_uuid`, a uuid4 string, unique (`models/mirror.py:70`).
- `schema/pull_request.mirrored.json` is a JSON Schema with `additionalProperties: false`.
- Ping body is `{event: 'ping', delivery_id}` (`delivery.py:334`). `webhooks.py:207-227` has a second ping implementation used by the route. It sends the same headers except the timestamp.

**Tests:** `tests/test_webhooks.py::test_delivery_signed_and_schema_valid`, `::test_schema_rejects_bad_events`, `::test_test_ping_signed`. `tests/test_delivery_outbox.py::test_stable_uuid_and_timestamp_header`, `::test_delivery_uuids_are_unique`.

---

## GM-11 Delivery is from an outbox: at-least-once with retries

**Actual behaviour:** Delivery rows are created in the same transaction as the mirrored PR. The timer loop claims up to 50 due `pending` rows (a lease of 50 x 10 s + 60 s), then POSTs each one. Success marks the row `delivered`. Failure adds one attempt and sets the backoff 30 s x 2^(attempts-1) (30, 60, 120, 240 s). After 5 attempts the row is `failed` and is not retried. There is no API route to retry. A helper function `requeue_failed` exists for manual use in a pod shell. Redirects are not followed, and a non-2xx or 3xx response counts as a failure. Error text stored is the exception class (plus the HTTP status), not the message.

**Evidence:**
- `app/delivery.py:337-360` `enqueue_deliveries` creates `pending` rows with `next_attempt_at=now`. It is called inside the PR transaction (`sync.py:288`).
- `app/delivery.py:274-280` `TIMEOUT 10`, `MAX_ATTEMPTS 5`, `BACKOFF_BASE 30s`, `BATCH_SIZE 50`, `LEASE`.
- `app/delivery.py:363-378` `claim_due_deliveries`: `FOR UPDATE SKIP LOCKED`, moves `next_attempt_at` forward by the lease, commits.
- `app/delivery.py:381-400` `process_due_deliveries` isolates each row in its own try/except.
- `app/delivery.py:411-422` `record_failure`. `delivery.py:425-436` `attempt_delivery`. A missing webhook or PR raises `LookupError` and counts as a failed attempt.
- `app/delivery.py:326-330` `allow_redirects=False`, and any non-2xx raises.
- `app/delivery.py:403-408` `error_label`. `delivery.py:439-455` `requeue_failed`.
- `app/models/mirror.py:73-82`: `status` check constraint (`pending`, `delivered`, `failed`) and indexes.
- `app/runner.py:77-81`: delivery is processed once per timer round after the mirror syncs.
- A row is not removed when the webhook is disabled after enqueue. `attempt_delivery` does not check `enabled`.

**Tests:** `tests/test_webhooks.py::test_retry_with_backoff_then_success`, `::test_failed_after_max_attempts`, `::test_secret_read_failure_counts_as_failed_attempt`. `tests/test_delivery_outbox.py::test_bad_secret_does_not_block_healthy_webhook`, `::test_unexpected_error_is_persisted_as_class_name`, `::test_two_runners_post_each_delivery_once`, `::test_lease_expires_so_crashed_runner_rows_retry`, `::test_redirect_is_not_followed_and_is_a_failure`, `::test_requeue_failed`, `::test_indexes_exist`, `::test_status_check_constraint`.

---

## GM-12 Webhook URL policy

**Actual behaviour:** On create and patch, the URL must be http or https, with no whitespace or control characters, no userinfo, and a valid port. The host must resolve. Every resolved address is checked. Loopback, link-local (including 169.254.169.254), unspecified, multicast, reserved, and the Kubernetes API server are always refused. Private ranges are allowed unless `GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE` is false-like (default is allow). The test-ping route re-checks the stored URL. The delivery path (`post_event`) does not re-check the URL.

**Evidence:**
- `app/webhooks.py:60-93` `check_webhook_url`. `webhooks.py:48-57` `check_address` (also unwraps IPv4-mapped IPv6). `webhooks.py:30-40` env `GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE`, default `'true'`.
- `webhooks.py:32, 81-82, 54-55`: hostnames `kubernetes.default[.svc[.cluster.local]]` and the `KUBERNETES_SERVICE_HOST` address are refused.
- `webhooks.py:131-135` URL check runs inside `validate_webhook` (create and patch). It returns 400.
- `webhooks.py:207-209` `send_ping` calls `check_webhook_url(webhook.url)` first. `allow_redirects=False` at `webhooks.py:223`.
- `app/delivery.py:312-330` `post_event` has no URL check.
- Max URL length is 512 (`webhooks.py:26`).

**Tests:** `tests/test_webhooks.py::test_webhook_url_policy_rejects`, `::test_webhook_url_rejects_kubernetes_service_host`, `::test_webhook_url_policy_allows_cluster_and_public`, `::test_webhook_private_ranges_can_be_disabled`, `::test_webhook_loopback_never_allowed_even_with_allow_private`, `::test_patch_url_is_revalidated`, `::test_test_ping_revalidates_stored_url`, `::test_test_ping_does_not_follow_redirects`, `::test_test_ping_passes_allow_redirects_false`.

---

## GM-13 Own database, own API, bearer token

**Actual behaviour:** The service has its own Postgres database `gitea_mirror` and its own HTTP API on port 5000. Every route except `GET /health` needs `Authorization: Bearer <token>`. The token comes from `GITEA_MIRROR_API_TOKEN`. The app refuses to start if it is empty. Errors are JSON `{"error": "..."}`.

**Evidence:**
- `app/__init__.py:17` `require_api_token(os.environ['GITEA_MIRROR_API_TOKEN'])`. `app/helpers/auth.py:8-12` raises `RuntimeError` on empty or blank.
- `app/__init__.py:24` `before_request` calls `check_bearer_token`. `helpers/auth.py:5` open endpoints are `{'main.health'}`. The compare is `hmac.compare_digest` on bytes (`auth.py:23-24`). A failure is 401.
- `app/helpers/errors.py:8-47`: 400, 401, 404, 409 and generic HTTP errors as JSON. `IntegrityError` becomes 409 "Conflicts with an existing record".
- Routes in `app/mirrors.py`:
  - `GET /mirrors` (200).
  - `POST /mirrors` (201, or 400/409).
  - `GET /mirrors/<id>`.
  - `PATCH /mirrors/<id>` (200, 400, 404, 409).
  - `DELETE /mirrors/<id>` (204).
  - `GET /mirrors/<id>/status` (200).
  - `POST /mirrors/<id>/resync`: 200 `{status, mirrored: [numbers]}`, 409 if busy, 502 on Gitea, git, GitHub or requests errors.
  - `POST /mirrors/<id>/users/sync` (200, 501, 502).
- Routes in `app/webhooks.py`: see GM-09.
- Mirror fields: `id, upstream_uri, secret_namespace, secret_key, gitea_owner, gitea_repo, base_branch, enabled` (`mirrors.py:18-21`). Unknown fields get 400 (`validation.py:66-68`). The unique keys are `upstream_uri` and `(gitea_owner, gitea_repo)` (`mirrors.py:38-48`, `models/mirror.py:13, 21-23`).
- `GET .../status` returns `cursor, last_sync_at, last_success_at, last_error, prs_mirrored, token_expired` (`mirrors.py:125-133`). `token_expired` is true when `last_error` contains `token_expired` or `bad credentials`.
- Create default is `enabled=True` (`mirrors.py:69`). The column server default is `false` (`models/mirror.py:19`).
- Migration: `migrations/versions/001_baseline.py` (one baseline, `alembic upgrade head` runs as a chart init container).
- Validation of Gitea names, branch names and k8s names: `app/helpers/validation.py:9-53`.

**Tests:** `tests/test_auth.py` (all). `tests/test_mirrors.py::test_missing_token_env_fails_fast`, `::test_auth_required`, `::test_health_needs_no_auth`, `::test_create_and_get`, `::test_create_bad_input`, `::test_create_not_json`, `::test_create_conflicts`, `::test_get_404`, `::test_patch`, `::test_patch_bad_and_conflict`, `::test_delete`, `::test_status`, `::test_status_with_state`. `tests/test_validation.py` (all). `tests/test_webhooks.py::test_auth_required`. `tests/test_sync.py::test_token_expired_recorded_and_flagged`.

---

## GM-14 Credentials are read by reference and passed safely

**Actual behaviour:** The API stores only a reference (`secret_namespace`, `secret_key`) for GitHub tokens and webhook HMAC keys. At use time the service reads the k8s secret with its own service account, taking field `token`. Both names are checked against a whitelist first. The git auth header goes to `git` through `GIT_CONFIG_*` env vars scoped to one host, never argv or the remote URL. Stored and shown error text is scrubbed of userinfo and the secret values. Sudo is only allowed for shadow users. API responses return the references, not values. The Gitea admin token and the API token come from env, filled from k8s secrets.

**Evidence:**
- `app/github.py:39-57` `read_secret_token`: `GET https://kubernetes.default.svc/api/v1/namespaces/<ns>/secrets/<name>` with the SA bearer token and cluster CA. It base64-decodes `data.token`. Names are validated at `github.py:44-46`.
- `app/delivery.py:285-287` `read_hmac_key` uses the same reader.
- `app/helpers/validation.py:17-20, 56-60` k8s name whitelists. They apply to mirrors and webhooks.
- `app/sync.py:119-143` header via env. `sync.py:139` the header and the bare token go into the scrub list.
- `app/sync.py:80-86` `scrub`. `sync.py:142` git errors are scrubbed. `sync.py:330` `last_error` is scrubbed.
- `app/sync.py:243-248, 239-241` Gitea push uses the same mechanism, scoped to the Gitea origin.
- `app/gitea.py:73-76` `git_remote` returns a URL without credentials plus the header value. `gitea.py:42-47` `segment()` validates path parts.
- `app/gitea.py:67` header `Authorization: token <GITEA_MIRROR_GITEA_TOKEN>`.
- `app/webhooks.py:236-237` ping errors return only the exception class name. `delivery.py:403-408` delivery errors keep only class and status.
- `k8s/.../gitea-mirror-rbac.yaml:187-223`: Role `get` on named secrets only, from `giteaMirror.secretAccess`.

**Tests:** `tests/test_sync_safety.py::test_github_header_is_scoped_to_github_and_not_in_argv`, `::test_header_not_sent_to_other_host_for_real`, `::test_gitea_header_also_via_env_only`, `::test_git_error_never_echoes_credentials`, `::test_scrub_removes_userinfo_and_secrets`, `::test_gitea_path_segments_are_validated`, `::test_repo_path_rejects_odd_segments`. `tests/test_sync.py::test_git_error_hides_auth_header`. `tests/test_webhooks.py::test_webhook_secret_ref_whitelist`, `::test_webhook_secret_read_errors_are_400_without_leak`, `::test_test_ping_does_not_leak_exception_text`, `::test_test_ping_secret_error_is_generic`. `k8s/federated-node/tests/gitea_mirror_test.yaml` "grants get on named secrets only..." (helm unittest).

---

## GM-15 Health and resilience

**Actual behaviour:** `GET /health` (no auth) runs `SELECT 1`. It returns 500 `{status: error}` if the DB fails. Under the container runner it also reports the sync loop: 200 `{status: ok, sync: {alive, last_tick_at}}` or 503 when the thread is dead or no tick has finished for 3 sync intervals. Each mirror is synced in isolation (one failure rolls back and moves on). A GitHub rate limit pauses only that mirror until the reset time. A busy mirror (lock held) is skipped. GitHub 5xx responses are retried 3 times. GitHub list pages use ETags and a 304 reuses the cached page. A failed run records `last_error` and the next round retries.

**Evidence:**
- `app/main.py:9-22` `/health`. `sync_status` extension exists only when set by the runner (`runner.py:101`).
- `app/runner.py:20-45` `STALE_FACTOR = 3`, `LoopStatus.snapshot`. `runner.py:48-83` `tick` (per-mirror try/except plus `rollback`, delivery round in its own try/except). `runner.py:86-94` `run_loop`.
- `app/runner.py:66-69` `RateLimited` sets `paused[mirror_id] = reset_at`, and `MirrorBusy` is ignored.
- `app/github.py:33-36, 113-123` `RateLimited` from 403/429 with `X-RateLimit-Remaining: 0` or `Retry-After`. `github.py:81` `Retry(total=3, backoff_factor=1, status_forcelist=(500,502,503,504))`. `github.py:90-111` ETag handling (in memory per process).
- `app/runner.py:99` interval from `GITEA_MIRROR_SYNC_INTERVAL_SECONDS` (chart default `"300"`, `values.yaml`).
- `app/sync.py:352-388` defines `tick` and `run_forever`, which duplicate the runner versions. `runner.py` does not call them.
- Chart probes: readiness and startup use `/health`. Liveness is a TCP check only (`gitea-mirror-deployment.yaml:91-107`).

**Tests:** `tests/test_health.py::test_health_endpoint`. `tests/test_delivery_outbox.py::test_health_without_loop_registered_is_ok`, `::test_health_reports_loop_state`, `::test_loop_thread_updates_heartbeat`, `::test_one_failing_mirror_does_not_stop_the_next`. `tests/test_sync.py::test_rate_limit_pauses_mirror_until_reset`, `::test_token_expired_recorded_and_flagged`, `::test_resync_busy_when_locked`. `tests/test_github_client.py::test_rate_limit_raises_with_reset_time`, `::test_rate_limit_429_retry_after`, `::test_401_is_token_expired`, `::test_etag_304_reuses_cached_page`, `::test_other_403_is_not_swallowed_on_pulls`.

---

## GM-16 Deployment: chart, RBAC, one replica

**Actual behaviour:** The chart deploys the service only when `giteaMirror.enabled` is true (default false). A `Deployment` named `gitea-mirror` is rendered, and it fails to render if `replicaCount` is not 1. An init container runs `alembic upgrade head`. The container is non-root, with a read-only root filesystem and all capabilities dropped. A `Service` is ClusterIP on port 5000. A `NetworkPolicy` limits ingress to same-namespace pods and egress to DNS, TCP 443 anywhere, Gitea, Postgres, and in-cluster webhook ports. RBAC gives the service account `get` on listed secrets only. A DB role and database `gitea_mirror` are created by a db-init job. The API token secret is generated once and kept on upgrade. The Gitea admin token is created by the `gitea-admin-init` job and stored as a secret (never overwritten). CI builds and tests the image.

**Evidence:**
- `k8s/federated-node/templates/gitea-mirror-deployment.yaml:1-4` fails if `replicaCount != 1`. Lines 24-52 init containers (pg wait only for in-cluster Postgres, then `db-migrations`). Lines 54-114 main container. Lines 115-121 `emptyDir` volumes: `tmp` (100Mi), `git-cache` (`cacheSizeLimit`, default 5Gi).
- Env set by the chart: `GITEA_MIRROR_DB_*` (`_helpers.tpl`), `GITEA_MIRROR_API_TOKEN` and `GITEA_MIRROR_GITEA_TOKEN` (from secrets), `GITEA_MIRROR_GITEA_URL = http://gitea.<ns>.svc:<gitea.service.http.port or 4000>` (`deployment.yaml:76-77`), `GITEA_MIRROR_GIT_CACHE_DIR=/tmp/git-cache`, plus `giteaMirror.env` (default `GITEA_MIRROR_SYNC_INTERVAL_SECONDS: "300"`).
- `gitea-mirror-networkpolicy.yaml`: Gitea egress is to pods labelled `app: gitea` on TCP 3000 (lines 158-165). Ingress is `podSelector: {}` on the service port. Webhook egress ports come from `giteaMirror.networkPolicy.webhookPorts` (default `[5000]`).
- `gitea-mirror-rbac.yaml:179-223`: ServiceAccount `gitea-mirror`. One Role and RoleBinding per `secretAccess` entry, `get` on `resourceNames`. Entries with no names grant nothing. Lines 225-266: SA `gitea-admin-init` with `get` on the token secret and `create` on secrets.
- `gitea-mirror-secrets.yaml`: API token secret `gitea-mirror-api-token` (key `token`), generated via `fn.dbPassword` if `apiToken.create`.
- `gitea-mirror-service.yaml`: ClusterIP, port `giteaMirror.port`.
- `templates/db-init-jobs.yaml`, `db-secrets.yaml`, `_helpers.tpl`: DB role/db `gitea_mirror`, password secret `gitea-mirror-db`.
- `templates/gitea-init-job.yaml`: when enabled, runs `gitea admin user generate-access-token --scopes write:admin,write:organization,write:repository,write:user,read:user`. It reads the secret first via the k8s API, keeps an existing one, and POSTs a new Secret expecting 201.
- `values.yaml` `giteaMirror:` block (default `enabled: false`). `values.schema.json` adds the schema for it.
- `.github/workflows/build.yml`: jobs `test-gitea-mirror` and `build-gitea-mirror-image`. The image `gitea_mirror` is added to the release image list.
- No other chart object changes beyond the above (no change to existing Gitea deployment).

**Tests:** `k8s/federated-node/tests/gitea_mirror_test.yaml` (helm unittest): "renders no mirror objects by default", "creates the gitea_mirror database, user and password secret", "deployment migrates, sets the env the app reads, and caches in an emptyDir", "refuses more than one replica", "the init job makes the gitea token secret only when the mirror is enabled", "the init job has no token step without the mirror", "service and generated api token secret", "grants get on named secrets only...", "gives each secretAccess entry its own Role and RoleBinding...", "lets the init job create the token secret and read only that one", "network policy limits ingress to the namespace and egress to what the service needs". Whether CI runs helm unittest on this file was not checked.

---

## GM-17 fncli mirror commands

**Actual behaviour:** `fncli mirror` is a click group registered in `fncli/cli.py`. It calls the service over HTTP with a bearer token. `MIRROR_URL` defaults to `http://localhost:5050` (port-forward) and `MIRROR_API_TOKEN` is required. HTTP errors show the service's `error` message and status. There is no redeliver or requeue command.

**Evidence:**
- `scripts/fncli/cmds/mirror.py:19-26` config (`MIRROR_URL`, `MIRROR_API_TOKEN`). `scripts/fncli/cmds/mirror.py:45-55` error wrapper.
- Commands:
  - `mirror add`: `--upstream-uri`, `--secret-namespace`, `--secret-key`, `--gitea-owner`, `--gitea-repo`, `--base-branch`, `--disabled`. It calls `POST /mirrors`.
  - `mirror list`, `status <id>`, `delete <id>`, `enable <id>`, `disable <id>`, `resync <id>`, `users-sync <id>`.
  - `mirror webhook add`: `--url`, `--secret-namespace`, `--secret-key`, `--mirror-id`, `--disabled`.
  - `mirror webhook list`, `deliveries <id> [--status pending|delivered|failed]`, `delete <id>`, `enable <id>`, `disable <id>`.
  - Enable and disable send `PATCH {enabled}`.
- `scripts/fncli/dagster/mirror.py:1-42` `MirrorAPI(HttpClient)`, one method per endpoint (no `webhooks/<id>/test` call).
- `scripts/fncli/cli.py` imports `mirror` and appends it to the module tuple.
- Docs added: `scripts/fncli/README.md`, `scripts/fncli/EXAMPLES.md`.

**Note (local worktree):** these files exist only on `origin/moonshot/gitea-mirror`. On `moonshot/shared-resources` there is no `scripts/fncli`, and `dagster/fncli` has no `mirror` command. The mirror code imports `fncli.dagster.utils` and `fncli.dagster.config`, which no longer exist there (it now uses `app.utils`, `app.config`). Not ported yet.

**Tests:** `scripts/fncli/tests/test_mirror.py`: `test_config_defaults_to_the_port_forwarded_service`, `test_the_token_is_required`, `test_add_posts_the_mirror`, `test_the_bearer_token_is_sent`, `test_an_in_cluster_url_goes_through_localhost`, `test_commands_call_their_endpoint`, `test_webhook_add_body`, `test_deliveries_filters_by_status`, `test_an_error_response_fails_the_command`, `test_enable_and_disable_patch_enabled`, `test_delete_reports_the_id`, `test_there_is_no_redeliver_command`, `test_the_services_error_message_is_shown`, `test_an_error_without_a_json_body_still_fails_cleanly`.

---

## GM-18 Mirror tests

**Actual behaviour:** The service has pytest tests in `gitea-mirror/tests/`. They run in Docker Compose with Postgres. The unit tests run in one script. Tests marked as needing a real Gitea are skipped unless `GITEA_MIRROR_GITEA_URL` is set, and a second script starts a real Gitea container for them. GitHub is simulated with the `responses` library and recorded JSON fixtures. A local bare git repo stands in for GitHub's git remote through `url.insteadOf`. CI runs both scripts.

**Evidence:**
- `gitea-mirror/run_tests.sh` (compose project `gm-test-*`; `ci` argument uses `docker-compose-tests-ci.yaml`).
- `gitea-mirror/run_gitea_tests.sh:1-34` starts `db` and `gitea`, creates admin `testadmin` and a token, then runs pytest. Default target is `tests/test_gitea_client.py`.
- Skip marks: `tests/test_sync_gitea.py:14`, `tests/test_gitea_client.py:5`, `tests/test_sync_robust_gitea.py:14` (`skipif GITEA_MIRROR_GITEA_URL not in env`).
- `.github/workflows/build.yml` `test-gitea-mirror`: `bash run_tests.sh ci`, then `bash run_gitea_tests.sh tests/test_gitea_client.py tests/test_sync_gitea.py tests/test_sync.py`. `test_sync_robust_gitea.py` is not in that CI list.
- Fixtures: `tests/fixtures/github/{contributors,collaborators,pulls_page1,pulls_page2}.json`, `tests/conftest.py`.
- Test files: `test_auth, test_delivery_outbox, test_gitea_client, test_github_client, test_health, test_mirrors, test_sync, test_sync_gitea, test_sync_robust_gitea, test_sync_safety, test_validation, test_webhooks`.
- Related tests elsewhere: `scripts/fncli/tests/test_mirror.py`, `k8s/federated-node/tests/gitea_mirror_test.yaml`.

**Tests:** Not applicable (this item describes the tests).

---

## GM-19 The node-side webhook receiver is not part of this build

**Actual behaviour:** Not found in code. Nothing in `webserver/`, `dagster/` or `scripts/` receives the mirror's webhook. The mirror only sends. The chart opens egress to in-cluster pods on `networkPolicy.webhookPorts` (default 5000). Tests use `http://receiver.invalid/hook` or mocked HTTP.

**Evidence:**
- Searched the whole snapshot (excluding `gitea-mirror/`) for `X-Gitea-Mirror`, `pull_request.mirrored`, `gitea-mirror`, `gitea_mirror`. The hits are only docs, `k8s/` chart files, `.github/workflows/build.yml`, and `scripts/fncli/` (mirror commands and tests).
- `k8s/federated-node/values.yaml` `giteaMirror.networkPolicy.webhookPorts: [5000]` (no receiver behind it).
- `tests/test_sync_gitea.py:100-101` registers `http://receiver.invalid/hook`.

**Tests:** none found.

---

---

# Built but not mapped

Behaviour in the code that no requirement ID covers.

### Shared-resources (SR)

**Project enable and backfill**
- `PATCH /projects/<id>` takes `enabled` and `backfill` (booleans). `backfill` is valid only with `"enabled": true` on a disabled project (400 otherwise) and is not stored. Turning a project on skips the gap, or with `backfill` creates the triggers of the pull requests stored while it was off. `POST /projects` creates a disabled project unless `enabled` is given; name unique, 409.
- `Project.in_flight_task_ids` counts tasks PENDING/QUEUED/RUNNING, SUCCESS with no result, or with a result IN_PROGRESS (`models/project.py:65-84`).
- `POST /projects/<pid>/tasks` is refused (409) while the project is disabled (`tasks_api.py:242-243`).
- The evaluate sensor and the launcher read enabled projects only; ingest does not look at projects (see SR-SENS-01, SR-SENS-08). Fan-out in the webserver skips a disabled project (`accepts_triggers`).
- Linking a results repository needs the project disabled (see SR-LINK). Other link changes and global resource edits are not gated.

**Webserver**
- API task trigger kind: `ApiRequestTrigger` with `user_id` and raw body (`models/api_request_trigger.py`). Triggers are polymorphic (`type` PR or API) with a table-level check on `state_cause` (`models/trigger.py`).
- `TaskSpec` rows: image, `dataset_id`, `env` (`models/task_spec.py`); env key regex, reserved keys and size cap (`dtos/task_spec.py:29-39`, constants in `helpers/const.py`).
- Task PATCH fields include `executor_run_id` (unique), `exit_code`, `state_cause`, `started_at`, `completed_at`.
- `GET /projects/<pid>/tasks` (not in `.../results`) returns `{tasks,total,page,per_page,pages}` with `?status=`.
- `GET /projects/<pid>/results?step=A&step=B` (repeatable).
- `results.attempts` and `results.error` fields; PR result fields branch, commit_sha, number, url, merged_at, merge_commit_sha.
- `GET /dagster/sensors`, `GET /dagster/sensors/<name>`, `PATCH /dagster/sensors` (`status` RUNNING|STOPPED, optional `names`), `PATCH /dagster/sensors/<name>`. Admin only. Talks to the Dagster GraphQL API; failure is 502 (`dagster_api.py`, `helpers/dagster.py`).
- `PATCH /delivery-secret`, task `cancel`, `logs`, `results/approve`, `results/block`: routes exist, return 501.
- Dataset `catalogue` and `dictionaries` are accepted on dataset POST/PATCH; datasets also create Keycloak resources (`models/dataset.py:190-262`).
- Audit: `@audit` records method, path, user, status, redacted body on most project/global routes; PR sub-routes and a few reads have no `@audit` (`project_trigger_repositories_api.py:236-301`).
- `/ready_check`, `/health_check` (Keycloak), `/login`, `/refresh_token`, Swagger UI at `/docs` from `static/openapi.json` (`main.py`, `__init__.py`).
- Whitelisted image checks are off unless `ENABLE_IMAGE_WHITELIST`; DAR checks are disconnected (TODO comments in `wrappers.py:35-39`, `models/task.py:134-137`).
- Registry check on task image (`Registry.validate_image_exist`).

**Dagster**
- `deliver_results_job` and `sync_results_pull_requests_job` in `definitions/sensors/task`; `evaluate_repository_pull_requests_job` in `definitions/sensors/git`.
- `k8s_pipes_job` and pipes client (`definitions/jobs.py`, `pipes.py`), optional pod security context from `DAGSTER_PIPES_*` env (`config.py:42-80`).
- Delivery commit author is `phems-bot` (`delivery/git_push.py:12-13`).
- `PullRequestResultStep.from_git` maps provider PR JSON to MERGED/CLOSED/OPENED (used by delivery and sync).

**fncli (`dagster/fncli`)**
- Commands (by module): `setup-project`, `teardown-project`, `setup-backend`, `teardown-backend`, `setup-gitea`, `teardown-gitea`, `open-pr` (`--kind watched|unwatched|invalid`, `--merge`, `--watch`); project, repo, secret, dataset init/delete; `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, `merge-gitea-pr`, `merge-results-pr`; `start-sensor`, `stop-sensor`, `sensor-status`; state commands (`project-show`, `project-set`, `link-set`, `global-set`, second project setup/teardown, `--expect STATUS`); `verify-project`, `verify-repo`, `project-healthcheck`; `hello-world`.
- `scripts/e2e_check.py` (wait-prs, wait-tasks, snapshot).
- `start-sensor --sensor all` starts every sensor, the reconcile sensor included; the order does not matter (`fncli/tests/test_sensor.py`).
- fncli ships inside the Dagster image (`dagster/.dockerignore` allows `fncli/**`).

**Other tooling**
- `scripts/deploy_owner.sh` (SR-DEV-05); `scripts/gitea.sh`, `init_repo.sh`, `init_pr.sh`, `merge_pr.sh`, `run_uc1_local.sh`, `dev.db/uc1_make_seed.sh`.
- Chart wires `DAGSTER_SENSORS_INITIAL_STATUS`, `RESULTS_MAX_ZIP_BYTES`, `DAGSTER_ARTIFACT_MOUNT_PATH`, `DAGSTER_WEBSERVER_URI` (`k8s/federated-node/templates/dagster-env-config.yaml:15-21`, `backend-configmap.yaml:28`). The chart has no Gitea-mirror template. Helm unit tests in `k8s/federated-node/tests` cover Keycloak, DB, subcharts and upgrades, not shared resources.

### Gitea-mirror (GM)

- **Manual retry helper.** `app/delivery.py:439-455` `requeue_failed(session, webhook_id=None)` resets `failed` rows to `pending`. It has no route and no fncli command. It is called only from tests.
- **Webhook test ping and delivery listing.** `POST /webhooks/<id>/test` and `GET /webhooks/<id>/deliveries` (`app/webhooks.py:230-249`).
- **Duplicate ping and timer code.** `app/webhooks.py:207-227` and `app/delivery.py:333-334` both define `send_ping`. `app/sync.py:352-388` `tick` and `run_forever` duplicate `app/runner.py:48-94`. Only the runner versions are used at startup.
- **Per-mirror ordering of failures.** `PullRequestsFailed` and quarantine of poison PRs (`sync.py:66-71, 302-316`). A quarantined PR gets no row, so it is retried every round while it is still above the cursor.
- **Branch collision guard.** An upstream branch named `pr` or `pr/<n>...` fails the sync with `BranchCollision` (`sync.py:62-63, 75, 192-200`).
- **Branch and name whitelists.** `check_branch_name` (`sync.py:89-101`) and `validation.py` regexes.
- **Git cache.** One bare repo per mirror at `<GITEA_MIRROR_GIT_CACHE_DIR>/<mirror_id>.git`, an `emptyDir` in the chart, re-fetched after a restart (`sync.py:151-165`).
- **Shadow user and org conflict handling.** Org named like a shadow user is refused (see the test list under GM-07).
- **Default-branch handling.** `set_default_branch` waits up to 20 s for the first push to land and sets the base branch as default (`gitea.py:142-154`).
- **`get_pull_request_files`.** Exists in `gitea.py:217-228` and is used only in tests.
- **Spike scripts.** `gitea-mirror/spike/00_prepare.sh` to `05_pullmirror.sh`, `common.sh`. They are shell scripts, not used by the app.
- **Dev-cluster ownership guard (outside gitea-mirror).** `scripts/deploy_owner.sh` (`claim`, `show`, `release`) records the owning worktree in ConfigMap `fn-dev-owner` (namespace `default`). `scripts/deploy.sh` and `scripts/upgrade.sh` call `claim`. `scripts/teardown.sh` calls `release`. `make deploy-owner` calls `show`. `FORCE_OWNER=1` overrides. Documented in `.tilt/TILT_QUICKSTART.md`.
- **`.worktreeinclude`.** New file listing `*.env`, `.env*`, `*.yaml`, `*.yml`.
- **fncli changes outside the `mirror` commands.** Only the import and registration lines in `scripts/fncli/cli.py`.
- **Other chart changes.** `gitea-init-job.yaml` now also creates the mirror's Gitea token (details under GM-16). It also drops the earlier `gitea admin user create` fallback shape; the create now sits in an `else` branch.
- **Other `requirements`.** `gitea-mirror/requirements-dev.txt`, `docker-compose-*.yaml`, `build/test.Dockerfile` (test tooling).
- **Gitea port (checked, fine).** The deployment uses service port 4000; the Gitea Service maps it to targetPort `http` (3000, `gitea-service.yaml:14-15`). The network policy allows the pod port 3000, which is the right one. The test script uses `gitea:3000` directly.
