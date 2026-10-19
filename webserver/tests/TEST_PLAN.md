# Route test plan (ADR 0019 layout)

> **Superseded.** This was the plan for the first 83 tests. Those tests were later merged into the condensed files in `tests/`
> (see `project/handover/shared-resources-tests-handover.md`), and the `IGNORED` state it mentions has been removed: a PR that does not
> match a link now creates no trigger. Kept for the fixture and trap notes; do not treat the tables below as current expectations.

One agent per file. Write ONLY your file. Never edit `conftest.py` or app code. If a test fails
because the app disagrees with this plan, leave the test as written, mark it
`@pytest.mark.xfail(reason="<what differs>")` and report it.

Status codes were checked by running or reading the code on 2026-10-16.

## Rules for every file

- Run: `cd webserver && source /tmp/fn_env.sh && timeout 300 .venv/bin/pytest tests/<your file> -q -p no:cacheprovider --no-cov -W ignore`
  (Postgres container `fn-routes-test-db`; `docker start fn-routes-test-db` if it is down).
- Request only `client`, `admin_headers` and the fixtures named in that test's setup column. The file-level "Fixtures:" list is a menu, not a parameter list (an extra `disabled_project` turns an expected 200 into 409 for a results link, or the reverse).
- Plain functions `def test_...(fixtures):`, no classes. Copy the style of `tests/test_smoke.py`.
- Requests: `client.get(url, headers=admin_headers)`, `client.put(url, json={...}, headers=admin_headers)`.
  Always pass `json=` (use `json={}` for an empty body) and `headers=admin_headers`.
- Errors come back as `{"error": "<message>"}`. Assert the status code; assert on the message only where the plan says so.
- To change a model in the test body: set the attribute, then `db.session.commit()`
  (`from app.helpers.base_model import db`).
- `pid` below means `project.id`; `T` = `global_trigger_repo.id`; `R` = `global_results_repo.id`; `D` = `global_dataset.id`.

## Fixtures (all in `conftest.py`, do not redefine)

| fixture | what it gives |
|---|---|
| `client` | Flask test client, fresh DB per test |
| `admin_headers` | admin bearer + JSON content type |
| `post_json_user_header` | NON-admin bearer + JSON. Only use it for the "revoked by non-admin -> 403" tests |
| `project`, `other_project` | two projects. Both are **enabled** |
| `disabled_project` | `project`, disabled (needed to link a results repository) |
| `enabled_project` | `project`, enabled (already the case; kept for older tests) |
| `global_secret` | Secret label `"test-creds"` (same object as `secret`). Every global_* resource below uses it |
| `make_global_secret(label=...)` | another secret. ALWAYS pass a label; the default `"test-creds"` already exists |
| `global_dataset` / `make_global_dataset(name=...)` | Dataset, unlinked. Names are stored lower-case (`"GlobalDs"` -> `"globalds"`) |
| `global_trigger_repo` / `make_trigger_repo(uri=...)` | TriggerRepository `github.com/org/triggers`, unlinked |
| `global_results_repo` / `make_results_repo(uri=...)` | ResultsRepository `github.com/org/results-global`, unlinked |
| `linked_secret`, `linked_dataset` | the link JSON after `PUT /projects/<pid>/secrets/test-creds` / `PUT /projects/<pid>/datasets/<D>` (201) |
| `linked_trigger_repo` | link JSON after `PUT /projects/<pid>/repositories/triggers/<T>` with `{"watch_dir": "triggers"}` (201) |
| `linked_results_repo` | link JSON after `PUT /projects/<pid>/repositories/results/<R>` with `{"target_dir": "results"}`; the fixture disables the project for the PUT and enables it again |
| `make_pr_batch(*numbers, **fields)` | body `{"pull_requests": [...]}`; defaults: merged 2030-01-01, base_branch `main`, adds `triggers/spec.json`. `fields` override every PR, e.g. `base_branch="dev"`, `changed_files=[{"path": "other/x.json", "status": "added"}]` |
| `ingest_prs(repo_id, *numbers, **fields)` | POSTs `make_pr_batch(...)` to `/global/repositories/triggers/<repo_id>/pull_requests`, asserts 201, returns `{"created": [...], "existing": [...]}` |
| `pr_trigger` | links T to `project`, ingests PR #1; returns the URL `/projects/<pid>/repositories/triggers/<T>/pull_requests/1`. Its state is `UNKNOWN` |
| `spec_raw` | valid PR spec file string: `'{"spec": {"image": "img:1"}}'` |
| `make_task(**fields)` | a Task in `project`, status `PENDING` |
| `k8s_client` | mocks the k8s secret calls; dict of mocks, e.g. `k8s_client["read_namespaced_secret_mock"]`, `k8s_client["delete_namespaced_secret_mock"]`. Secret data keys: USERNAME, PASSWORD, USER, TOKEN |
| `mock_connection_checks` | healthchecks: every repository and dataset check returns OK. Dict with `"repository"` and `"dataset"` mocks |

## Traps (read before writing)

1. **Link first, then ingest.** A new link's cursor is its creation time (or the latest stored PR). PRs ingested *before* the link are never given a trigger. `make_pr_batch` merges in 2030 so PRs ingested after linking are in scope.
2. **Disabled-project rule.** Linking a results repository (even the first one) needs the project disabled, otherwise **409**. Every other link change (first PUT, relink, PATCH, DELETE) is allowed in any state.
3. **In-flight tasks.** A task with status `PENDING`/`QUEUED`/`RUNNING` (e.g. any `make_task()` or a task made by `/task`) blocks nothing: tasks are pinned to the configuration they were created with.
4. **403 only for `revoked`.** The test Keycloak mock lets the non-admin token through every scope, so the ONLY 403 test is a non-admin PATCH with `{"revoked": ...}` using `post_json_user_header`. Do not write other 403 tests.
5. **"Cross-project" means 404.** Asking `other_project` for a link that only `project` has returns 404.
6. **`?active_link=true` needs an enabled project.** Use `enabled_project`, otherwise the list is empty.
7. Fixtures are lazy: a test only gets a link if it requests `linked_*` (or `pr_trigger`) as a parameter.
8. Never request `disabled_project` together with `linked_results_repo`: that fixture enables the project when it finishes. Disable it in the test body instead (`project.enabled = False`, `db.session.commit()`) after the link exists.
9. Several global resources reuse `test-creds`, so `DELETE /global/secrets/test-creds` is 409 whenever any `global_*` repo/dataset fixture is requested.

---

## 1. `tests/test_global_trigger_repositories.py` (10 tests)

Fixtures: `client, admin_headers, global_secret, global_trigger_repo, make_trigger_repo, project, enabled_project, linked_trigger_repo`.
Base URL `/global/repositories/triggers`.

| test | setup | request | assert |
|---|---|---|---|
| `test_create` | `global_secret` | POST base `{"uri": "github.com/org/new", "provider": "github", "secret_label": "test-creds"}` | 201; `uri == "github.com/org/new"`, `api_uri == "https://api.github.com"`, `enabled is True`, `secret["label"] == "test-creds"` |
| `test_create_duplicate_uri_conflicts` | POST the same body twice, the second with `"uri": "https://github.com/org/new"` | second POST | 409 |
| `test_create_unknown_secret` | `global_secret` | POST with `"secret_label": "nope"` | **400** (a referenced secret that is missing is 400, not 404) |
| `test_create_bad_provider` | | POST with `"provider": "bogus"` | 400 |
| `test_create_refuses_watch_dir` | | POST valid body plus `"watch_dir": "x"` | 400 |
| `test_get_one_and_404` | `global_trigger_repo` | GET `base/<T>`, then GET `base/999` | 200 with `id == T`; then 404 |
| `test_list_active_link_filter` | `enabled_project`, `linked_trigger_repo`, plus `make_trigger_repo(uri="github.com/org/unlinked")` | GET `base`, then GET `base?active_link=true` | first: ids == `[T, unlinked.id]`; second: ids == `[T]` |
| `test_active_link_excludes_revoked_link` | `enabled_project`, `linked_trigger_repo` | PATCH `/projects/<pid>/repositories/triggers/<T>` `{"revoked": true}` (200), then GET `base?active_link=true` | `[]` |
| `test_patch_enabled_and_secret_label` | `linked_trigger_repo` | PATCH `base/<T>` `{"enabled": false}`; then PATCH `base/<T>` `{"secret_label": "test-creds"}` | 200; then 200 |
| `test_delete_needs_force_when_linked` | `linked_trigger_repo` | DELETE `base/<T>`; then DELETE `base/<T>?force=true`; then GET `base/<T>` | 409; 204; 404 |

## 2. `tests/test_pull_request_ingest.py` (10 tests)

Fixtures: `client, admin_headers, project, other_project, global_trigger_repo, linked_trigger_repo, make_pr_batch, ingest_prs`.
Ingest URL `I = /global/repositories/triggers/<T>/pull_requests`; project PR list `L = /projects/<pid>/repositories/triggers/<T>/pull_requests`.

| test | setup | request | assert |
|---|---|---|---|
| `test_ingest_creates_and_fans_out` | `linked_trigger_repo` | POST `I` `make_pr_batch(1, 2)` | 201, `{"created": [1, 2], "existing": []}`; GET `L` -> `total == 2`, every item `state == "UNKNOWN"` |
| `test_ingest_is_idempotent` | `linked_trigger_repo`; `ingest_prs(T, 1)` | POST `I` `make_pr_batch(1, 2)` | 201, `created == [2]`, `existing == [1]`; GET `L` -> `total == 2` |
| `test_other_base_branch_is_ignored` | `linked_trigger_repo` | `ingest_prs(T, 3, base_branch="dev")`, GET `L/3` | 200, `state == "IGNORED"`, `"dev"` in `state_cause` |
| `test_file_outside_watch_dir_is_ignored` | `linked_trigger_repo` | `ingest_prs(T, 4, changed_files=[{"path": "other/spec.json", "status": "added"}])`, GET `L/4` | `state == "IGNORED"`, `state_cause` contains `"triggers"` |
| `test_truncated_files_match` | `linked_trigger_repo` | `ingest_prs(T, 5, changed_files=[], files_truncated=True)`, GET `L/5` | `state == "UNKNOWN"` |
| `test_no_link_stores_but_no_triggers` | `global_trigger_repo` only | POST `I` `make_pr_batch(1)`; GET `/global/repositories/triggers/<T>/pull_requests` | 201 `created == [1]`; global list `total == 1` |
| `test_revoked_link_gets_no_trigger` | `linked_trigger_repo`; PATCH `/projects/<pid>/repositories/triggers/<T>` `{"revoked": true}` (200) | `ingest_prs(T, 1)`; GET `L` | `total == 0` |
| `test_disabled_repo_refused` | `global_trigger_repo.enabled = False`; commit | POST `I` `make_pr_batch(1)` | 400; `"disabled"` in `error` |
| `test_bad_bodies` | `global_trigger_repo` | (a) `{"pull_requests": "x"}`; (b) `make_pr_batch(*range(1, 102))`; (c) `make_pr_batch(1)` with `del body["pull_requests"][0]["title"]` | all 400 |
| `test_unknown_repo` | | POST `/global/repositories/triggers/999/pull_requests` `make_pr_batch(1)` | 404 |

## 3. `tests/test_project_trigger_links.py` (10 tests)

Fixtures: `client, admin_headers, post_json_user_header, project, other_project, global_trigger_repo, linked_trigger_repo, ingest_prs, make_task`.
`U = /projects/<pid>/repositories/triggers/<T>`.

| test | setup | request | assert |
|---|---|---|---|
| `test_link_returns_201_and_lists` | `global_trigger_repo` | PUT `U` `{"watch_dir": "triggers", "base_branch": "release"}`; GET `/projects/<pid>/repositories/triggers` | 201, `watch_dir == "triggers"`, `base_branch == "release"`, `active is True`, `trigger_repository["id"] == T`; list has 1 item |
| `test_link_bad_body` | `global_trigger_repo` | PUT `U` `{}`; PUT `U` `{"watch_dir": "x", "bogus": 1}` | 400, 400 |
| `test_link_unknown_repo_or_project` | `project` | PUT `/projects/<pid>/repositories/triggers/999` `{"watch_dir": "x"}`; PUT `/projects/999/repositories/triggers/<T>` same body (needs `global_trigger_repo`) | 404, 404 |
| `test_relink_returns_200` | `linked_trigger_repo` | PUT `U` `{"watch_dir": "other"}` | 200, `watch_dir == "other"` |
| `test_other_project_cannot_see_link` | `linked_trigger_repo`, `other_project` | GET `/projects/<other_project.id>/repositories/triggers/<T>` | 404 |
| `test_revoke_admin_only` | `linked_trigger_repo` | PATCH `U` `{"revoked": true}` with `post_json_user_header`; then with `admin_headers` | 403; then 200 with `revoked is True`, `active is False` |
| `test_unrevoke_skips_the_gap` | `linked_trigger_repo`; PATCH `U` `{"revoked": true}`; `ingest_prs(T, 1)` | PATCH `U` `{"revoked": false}` | 200, `active is True`, `pr_count == 0`; the PR stays stored |
| `test_disable_and_enable_with_a_task_in_flight` | `linked_trigger_repo` | PATCH `U` `{"enabled": false}`; then `make_task()`; PATCH `U` `{"enabled": true}` | 200 `enabled is False`; then 200 `enabled is True` |
| `test_unlink` | `linked_trigger_repo` | DELETE `U`; GET `U` | 204; 404 |

## 4. `tests/test_project_pull_requests_and_tasks.py` (12 tests)

Fixtures: `client, admin_headers, project, global_trigger_repo, pr_trigger, ingest_prs, spec_raw, linked_dataset, global_dataset`.
`P = pr_trigger` (URL of PR #1); `L = /projects/<pid>/repositories/triggers/<T>/pull_requests`.

| test | setup | request | assert |
|---|---|---|---|
| `test_list_and_get_pr` | `pr_trigger` | GET `L`; GET `P` | 200, `total == 1`, `items[0]["number"] == 1`; 200, `state == "UNKNOWN"`, `task_id is None` |
| `test_list_filter_by_state` | `pr_trigger`; `ingest_prs(T, 2, base_branch="dev")` | GET `L?state=IGNORED`; GET `L?state=NOPE` | `total == 1`, `items[0]["number"] == 2`; 400 |
| `test_get_unknown_pr` | `pr_trigger` | GET `L/99` | 404 |
| `test_patch_state` | `pr_trigger` | PATCH `P` `{"state": "REJECTED", "state_cause": "bad"}` | 200, `state == "REJECTED"`, `state_cause == "bad"` |
| `test_patch_bad_state` | `pr_trigger` | PATCH `P` `{"state": "BOGUS"}`; PATCH `P` `{"state": "REJECTED"}` (no cause) | 400; 400 |
| `test_create_task` | `pr_trigger` | POST `P + "/task"` `{"spec_raw": spec_raw}`; GET `P` | 201, `status == "PENDING"`, `spec["image"] == "img:1"`, `project_id == pid`, `name == "PR 1"`; PR now `state == "YIELDED"`, `task_id == <task id>` |
| `test_create_task_is_idempotent` | `pr_trigger`; POST task once | POST `P + "/task"` again | 200, same `id` |
| `test_task_gets_default_dataset` | request `linked_dataset` BEFORE `pr_trigger` in the parameter list | POST `P + "/task"` `{"spec_raw": spec_raw}` | 201, `spec["dataset_id"] == D` |
| `test_bad_spec_rejects_pr` | `pr_trigger` | POST `P + "/task"` `{"spec_raw": "{}"}`; GET `P` | 400; PR `state == "REJECTED"`, `"spec"` in `state_cause` |
| `test_missing_spec_raw` | `pr_trigger` | POST `P + "/task"` `{}` | 400 |
| `test_tasks_routes` | `pr_trigger`; create task (201) -> `tid` | GET `/projects/<pid>/tasks`; GET `/projects/<pid>/tasks/<tid>`; GET `/projects/<pid>/tasks/999` | 200 with `total == 1`, `tasks[0]["id"] == tid`; 200; 404 |
| `test_patch_task` | as above | PATCH `/projects/<pid>/tasks/<tid>` `{"status": "RUNNING", "executor_run_id": "run-1"}`; PATCH `/projects/<pid>/tasks/<tid>` `{"bogus": 1}`; GET `/projects/<pid>/tasks/<tid>/results` | 200 `status == "RUNNING"`, `executor_run_id == "run-1"`; 400; 200 `[]` |

## 5. `tests/test_datasets.py` (10 tests)

Fixtures: `client, admin_headers, project, other_project, global_secret, global_dataset, linked_dataset, post_json_user_header`.
`G = /global/datasets`; `U = /projects/<pid>/datasets/<D>`.

| test | setup | request | assert |
|---|---|---|---|
| `test_create` | `global_secret` | POST `G` `{"name": "NewDs", "host": "db", "port": 5432, "secret_label": "test-creds"}` | 201, `name == "newds"`, `enabled is True`, `secret["label"] == "test-creds"` |
| `test_create_refuses_credentials_and_project` | `global_secret` | POST valid body plus `"username": "u"`; POST valid body plus `"project_id": 1` | 400; 400 |
| `test_create_needs_secret_label` | | POST `{"name": "X", "host": "db", "port": 5432}` | 400 |
| `test_list_and_get` | `global_dataset` | GET `G`; GET `G/<D>`; GET `G/999` | 200, `total == 1`, `items[0]["id"] == D`; 200 `name == "globalds"`; 404 |
| `test_patch_and_delete` | `linked_dataset` | PATCH `G/<D>` `{"host": "new"}`; DELETE `G/<D>?force=true` | 200, `host == "new"`; 204 |
| `test_link_and_list` | `global_dataset` | PUT `U` `{}`; GET `/projects/<pid>/datasets`; GET `U` | 201 `active is True`, `dataset["id"] == D`; list length 1; 200 |
| `test_link_errors` | `global_dataset`, `other_project` | PUT `/projects/<pid>/datasets/999` `{}`; PUT `U` `{"bogus": 1}`; GET `/projects/<other_project.id>/datasets/<D>` | 404; 400; 404 |
| `test_revoke_admin_only` | `linked_dataset` | PATCH `U` `{"revoked": true}` with `post_json_user_header`; then with `admin_headers` | 403; 200 `active is False` |
| `test_disable_link_and_unlink` | `linked_dataset` | PATCH `U` `{"enabled": false}` -> 200 `active is False`; DELETE `U` -> 204 | as listed |

## 6. `tests/test_secrets.py` (10 tests)

Fixtures: `client, admin_headers, post_json_user_header, k8s_client, project, other_project, global_secret, linked_secret, global_trigger_repo`.
`G = /global/secrets`; `U = /projects/<pid>/secrets/<label>`. **Always request `k8s_client`** in POST/PATCH-values/DELETE tests (it mocks the secret store).
Body helper: `NEW = {"label": "new-creds", "provider": "K8S", "values": {"TOKEN": "t"}}`.

| test | setup | request | assert |
|---|---|---|---|
| `test_create` | `k8s_client` | POST `G` `NEW` | 201, `label == "new-creds"`, `key == "fn-secret-new-creds"`, `"values" not in` response; `k8s_client["create_namespaced_secret_mock"].called` |
| `test_create_duplicate_conflicts` | `k8s_client`; POST `NEW` | POST `NEW` again | 409 |
| `test_create_bad_bodies` | `k8s_client` | POST `{"label": "x", "provider": "K8S"}` (no values); POST `{"label": "x", "provider": "NOPE", "values": {"TOKEN": "t"}}` | 400; 400 |
| `test_list_and_get` | `global_secret` | GET `G`; GET `G/test-creds`; GET `G/nope` | 200, labels == `["test-creds"]`; 200; 404 |
| `test_rotate_and_disable` | `k8s_client`; POST `NEW` | PATCH `G/new-creds` `{"values": {"TOKEN": "t2"}}`; PATCH `G/new-creds` `{"enabled": false}` | 200; 200 `enabled is False` |
| `test_delete_in_use_conflicts` | `global_trigger_repo` (uses test-creds) | DELETE `G/test-creds` | 409 |
| `test_delete` | `k8s_client`; POST `NEW` | DELETE `G/new-creds`; GET `G/new-creds` | 204, `k8s_client["delete_namespaced_secret_mock"].called`; 404 |
| `test_link_and_get` | `global_secret` | PUT `/projects/<pid>/secrets/test-creds` `{}`; GET same; GET `/projects/<pid>/secrets` | 201 `active is True`, `secret["label"] == "test-creds"`; 200; list length 1 |
| `test_link_errors` | `linked_secret`, `other_project` | PUT `/projects/<pid>/secrets/nope` `{}`; PUT `/projects/<pid>/secrets/test-creds` `{}` again; GET `/projects/<other_project.id>/secrets/test-creds` | 404; 200; 404 |
| `test_revoke_and_unlink` | `linked_secret` | PATCH `U` `{"revoked": true}` with `post_json_user_header` -> 403; with `admin_headers` -> 200 `active is False`; DELETE `U` -> 204 | as listed |

## 7. `tests/test_results.py` (11 tests)

Fixtures: `client, admin_headers, project, other_project, disabled_project, global_secret, global_results_repo, make_results_repo, linked_results_repo, make_task, global_trigger_repo`.
`G = /global/repositories/results`; `U = /projects/<pid>/repositories/results/<R>`; `RES = /projects/<pid>/results`.
**Trap:** the results-repository PUT needs the project disabled even for the first link (409 otherwise). `linked_results_repo` handles that and enables the project again after.

| test | setup | request | assert |
|---|---|---|---|
| `test_create_global` | `global_secret` | POST `G` `{"uri": "github.com/org/r2", "provider": "github", "secret_label": "test-creds"}`; same again; POST with extra `"target_dir": "x"` and uri `github.com/org/r3` | 201 `uri == "github.com/org/r2"`; 409; 400 |
| `test_get_global_and_404` | `global_results_repo` | GET `G/<R>`; GET `G/999` | 200; 404 |
| `test_link_needs_a_disabled_project` | `project`, `global_results_repo` | PUT `U` `{"target_dir": "results"}` | 409, `error` says the project must be disabled |
| `test_link_disabled_project` | `disabled_project`, `global_results_repo` | PUT `U` `{"target_dir": "results"}`; PUT `U` `{"target_dir": "out"}`; GET `/projects/<pid>/repositories/results` | 201; 200 `target_dir == "out"`; list length 1 |
| `test_second_results_repo_conflicts` | `disabled_project`; PUT `U` (201); `other = make_results_repo(uri="github.com/org/other")` | PUT `/projects/<pid>/repositories/results/<other.id>` `{"target_dir": "r"}` | 409 |
| `test_link_into_watched_dir_refused` | `disabled_project`; PUT `/projects/<pid>/repositories/triggers/<T>` `{"watch_dir": "triggers"}` (201); `loop = make_results_repo(uri="github.com/org/triggers")` | PUT `/projects/<pid>/repositories/results/<loop.id>` `{"target_dir": "triggers/out"}` | 400, `"overlap"` in `error` |
| `test_post_result` | `linked_results_repo`; `task = make_task()` | POST `RES` `{"task_id": task.id, "results_repository_id": R}`; same again | 201 `step == "UNKNOWN"`, `state == "IN_PROGRESS"`, `results_repository_id == R`, `type == "PR"`; 200 same `id` |
| `test_post_result_errors` | `linked_results_repo`; `task = make_task()` | (a) `results_repository_id: 999`; (b) `task_id: 999`; (c) `task_id: "x"`; (d) same valid body to `/projects/<other_project.id>/results` | (a) **400** (unlinked repo is 400, not 404); (b) 404; (c) 400; (d) 404 |
| `test_patch_result` | post a result -> `rid` | PATCH `RES/<rid>` `{"step": "OPENED", "number": 5, "url": "https://x/pull/5"}`; PATCH `{"step": "PUSHED"}`; PATCH `{"bogus": 1}` | 200 `step == "OPENED"`, `number == 5`; 400 (step only moves forward); 400 |
| `test_results_by_step_and_cross_project` | post + PATCH to `OPENED` -> `rid` | GET `RES?step=OPENED`; GET `RES?step=PUSHED`; GET `RES?step=NOPE`; PATCH `/projects/<other_project.id>/results/<rid>` `{"step": "MERGED"}` | len 1; len 0; 400; 404 |
| `test_revoke_and_unlink_results_repo` | `linked_results_repo` | PATCH `U` `{"revoked": true}` (admin) -> 200 `active is False`; DELETE `U` -> 204 | as listed |

## 8. `tests/test_healthchecks.py` (9 tests)

Fixtures: `client, admin_headers, k8s_client, mock_connection_checks, project, other_project, global_secret, global_dataset, global_trigger_repo, global_results_repo, linked_trigger_repo, linked_results_repo, linked_secret, linked_dataset`.
**Always request both `k8s_client` and `mock_connection_checks`** (otherwise the test makes real network calls).
To fail a repository check: `from app.models.git_provider import ConnectionCheck, ConnectionStatus` then
`mock_connection_checks["repository"].return_value = lambda: ConnectionCheck(ConnectionStatus.UNAUTHORIZED, "Unauthorized", 401)`.
To make a secret missing: `from kubernetes.client.exceptions import ApiException` then `k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)`.
A failed check is still **200**; the failure is in the body.

| test | setup | request | assert |
|---|---|---|---|
| `test_global_healthcheck_ok` | `global_dataset, global_trigger_repo, global_results_repo` | GET `/global/healthcheck` | 200, `status == "ok"`, one item each in `datasets`, `secrets`, `trigger_repositories`, `results_repositories`, each `status == "ok"` |
| `test_global_healthcheck_reports_failure` | as above; make repository check UNAUTHORIZED | GET `/global/healthcheck` | 200, `status == "error"`, `trigger_repositories[0]["status"] == "unauthorized"` |
| `test_resource_healthchecks` | `global_dataset, global_trigger_repo, global_results_repo` | GET `/global/datasets/<D>/healthcheck`, `/global/secrets/test-creds/healthcheck`, `/global/repositories/triggers/<T>/healthcheck`, `/global/repositories/results/<R>/healthcheck` | each 200, `status == "ok"` |
| `test_resource_healthcheck_404` | | GET `/global/repositories/triggers/999/healthcheck`; GET `/global/secrets/nope/healthcheck` | 404; 404 |
| `test_secret_missing` | `global_trigger_repo`; secret missing (side_effect above) | GET `/global/secrets/test-creds/healthcheck` | 200, `status == "secret_missing"`, `keys == []`, `"TOKEN"` in `missing_keys` |
| `test_project_healthcheck` | `linked_trigger_repo`, `linked_results_repo` | GET `/projects/<pid>/healthcheck` | 200, `status == "ok"`, `trigger_repositories[0]["id"] == T`, `results_repository["target_dir"] == "results"` |
| `test_project_healthcheck_no_links_is_error` | `other_project` | GET `/projects/<other_project.id>/healthcheck` | 200, `status == "error"`, `trigger_repositories == []`, `results_repository is None` |
| `test_link_healthchecks` | all four `linked_*` | GET `/projects/<pid>/datasets/<D>/healthcheck`, `/projects/<pid>/secrets/test-creds/healthcheck`, `/projects/<pid>/repositories/triggers/<T>/healthcheck`, `/projects/<pid>/repositories/results/<R>/healthcheck` | each 200, `active is True`, `project_id == pid` |
| `test_link_healthcheck_other_project_404` | `linked_trigger_repo`, `other_project` | GET `/projects/<other_project.id>/repositories/triggers/<T>/healthcheck` | 404 |

## 9. `tests/test_e2e_flow.py` (1 test)

Fixtures: `client, admin_headers, k8s_client, disabled_project, make_pr_batch, spec_raw`. Do NOT use the global_*/linked_* fixtures; everything goes through the API. Assert every step's status code (`assert r.status_code == X, r.json`).

`test_full_flow`, steps in this exact order:

1. POST `/global/secrets` `{"label": "e2e-creds", "provider": "K8S", "values": {"TOKEN": "t", "USERNAME": "u", "PASSWORD": "p"}}` -> 201.
2. POST `/global/repositories/triggers` `{"uri": "github.com/org/e2e-triggers", "provider": "github", "secret_label": "e2e-creds"}` -> 201, `T = r.json["id"]`.
3. POST `/global/repositories/results` `{"uri": "github.com/org/e2e-results", "provider": "github", "secret_label": "e2e-creds"}` -> 201, `R = r.json["id"]`.
4. POST `/global/datasets` `{"name": "E2eDs", "host": "db", "port": 5432, "secret_label": "e2e-creds"}` -> 201, `D = r.json["id"]`.
5. PUT `/projects/<pid>/secrets/e2e-creds` `{}` -> 201.
6. PUT `/projects/<pid>/datasets/<D>` `{}` -> 201.
7. PUT `/projects/<pid>/repositories/triggers/<T>` `{"watch_dir": "triggers"}` -> 201.
8. (nothing: the project is already disabled, as a new one is)
9. PUT `/projects/<pid>/repositories/results/<R>` `{"target_dir": "results"}` -> 201.
10. PATCH `/projects/<pid>` `{"enabled": true}` -> 200, `enabled is True`.
11. GET `/global/repositories/triggers?active_link=true` -> 200, ids == `[T]`.
12. `batch = make_pr_batch(1, 2)`; `batch["pull_requests"] += make_pr_batch(3, base_branch="dev")["pull_requests"]`; POST `/global/repositories/triggers/<T>/pull_requests` batch -> 201, `created == [1, 2, 3]`.
13. GET `/projects/<pid>/repositories/triggers/<T>/pull_requests` -> `total == 3`; states by number: `{1: "UNKNOWN", 2: "UNKNOWN", 3: "IGNORED"}`.
14. POST `/projects/<pid>/repositories/triggers/<T>/pull_requests/1/task` `{"spec_raw": spec_raw}` -> 201, `spec["dataset_id"] == D`, `tid = r.json["id"]`.
15. PATCH `/projects/<pid>/tasks/<tid>` `{"status": "SUCCESS"}` -> 200.
16. POST `/projects/<pid>/results` `{"task_id": tid, "results_repository_id": R}` -> 201, `rid = r.json["id"]`.
17. PATCH `/projects/<pid>/results/<rid>` `{"step": "OPENED", "state": "DELIVERED", "number": 7, "url": "https://github.com/org/e2e-results/pull/7"}` -> 200, `step == "OPENED"`, `state == "DELIVERED"`.
18. GET `/projects/<pid>/tasks/<tid>/results` -> 200, length 1, `[0]["results_repository_id"] == R`.
19. GET `/projects/<pid>/results?step=OPENED` -> 200, length 1.

---

Total: 10 + 10 + 10 + 12 + 10 + 10 + 11 + 9 + 1 = **83 tests**.

## Known failures in the existing suite (not for these agents)

- `tests/test_dtos.py::TestDatasetDTO::test_fields` expects no `enabled` field; `test_slug_and_url_are_derived` expects `url` to end with `/datasets/<slug>`, but it is now `/global/datasets/<id>`. Stale tests.
