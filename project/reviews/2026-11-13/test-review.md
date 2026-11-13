# Test suite review (8-minute, read-only pass)

Nothing was run. Every item was confirmed by reading the test and the code it targets, unless marked "not verified".

## 1. Tests that cannot fail or assert nothing useful

- `nexus/api/tests/test_live_client_integration.py:22` - `REPO_ROOT = parents[2]` is `nexus/`, not the repo root, so `DAGSTER_DIR` is `nexus/dagster` (does not exist) and line 26 skips the whole module. In the docker run only `./tests` and `./app` are mounted (`nexus/api/docker-compose-tests.yaml:8-9`), so it is skipped there too. The module that checks the real Dagster and fncli clients against the live app never runs anywhere.
  Fix: `parents[3]`, and mount `dagster/` read-only in the test compose (or run this module in a CI job that has the full checkout). Make the skip a failure in CI.
- `nexus/api/tests/test_all_tasks_list.py:92` and `nexus/api/tests/test_task_launch.py:19` - same `parents[2]` mistake for `CONTRACT`; the `skipif` at `test_all_tasks_list.py:101` and `test_task_launch.py:192` is therefore always true. The two contract-shape tests never run.
  Fix: `parents[3]` (as `test_task_run_resources.py:17` already does), plus the mount above.
- `nexus/api/tests/test_task_run_resources.py:17` - uses `parents[3]`, which is right in a checkout, but in the container the file is `/app/tests/...`, which only has 3 parents, so `parents[3]` should raise `IndexError` at import. Not verified (did not check the image's workdir or CI output).
  Fix: compute the root once in `conftest.py` with a guard and share it across the four files.
- `nexus/api/tests/test_live_client_integration.py:218-223` - `test_fncli_login_returns_token` catches `HTTPError` and calls `pytest.xfail`, then only asserts `isinstance(data, dict)`. It cannot fail on a broken `/login`.
  Fix: make the mocked Keycloak serve `/login` and assert the token field; drop the try/except.
- `dagster/app/tests/test_task_run_status_sensor.py:127` - `test_a_409_from_a_finished_task_is_skipped` has no assert. It passes if the sensor never calls `patch_task` at all.
  Fix: add `backend_api.patch_task.assert_called_once()`.
- `nexus/api/tests/test_smoke.py:29-31` - `test_reset_password_needs_no_token` asserts `status_code not in (401, 404)`; an empty body going into `kc.get_user_by_email(email=None)` (`nexus/api/app/users_api.py:54-66`) can return 500 and still pass.
  Fix: mock Keycloak and assert 204; add a bad-body case with the expected 4xx.
- `nexus/api/tests/test_state_rules.py:23-30, 50-57` - `test_trigger_moves` and `test_result_moves` compute the expected outcome from `TRIGGER_MOVES` / `RESULT_ORDER` themselves, with the same expression as `transition()` / `forward_only()` (`nexus/api/app/helpers/state_rules.py:8-20`). Editing a table (e.g. allowing `YIELDED -> REJECTED`) cannot fail them. Only `TASK_MOVES` has an independent check (line 35 hardcodes the final states, line 44 the order).
  Fix: pin the tables with literal expected pairs (allowed and refused) for triggers and result steps.
- `nexus/api/tests/keycloak/test_permission_model.py:34,45,97,108,154,165,204,215`, `test_clients.py:124,177`, `test_keycloak_helper.py:285,354`, `test_keycloak_users.py:218,263` - no asserts ("no exception is raised"), and the fixture uses `RequestsMock(assert_all_requests_are_fired=False)` (`test_keycloak_helper.py:26`). `test_create_policy_409_accepted` says it checks the existing policy is fetched, but nothing asserts the GET happened.
  Fix: assert the return value, or `rsps.assert_call_count(url, 1)` for the follow-up request.
- `nexus/api/tests/tasks/test_resource_validators.py:9,28` - "valid values accepted" tests with no assert on what `Task.validate` returns. Low value, cheap to fix by asserting the normalised resources.

## 2. Important behaviour with no test

- `nexus/api/app/dagster_api.py:44-88` - all four `/dagster/sensors` routes (list, get one, bulk PATCH, single PATCH) have no test: no hit for `/sensors`, `list_sensors` or `set_sensor_status` in `nexus/api/tests`. Untested paths include the bad `status` 400, `names` not a list, unknown names 404, and "only changes sensors whose status differs".
- `nexus/api/app/users_api.py:20-52` - `POST /global/users` (missing email, existing user, username defaulting to email, temp password) has no route test. `GET /global/users` (line 70) has none either. Only the Keycloak helper underneath is tested (`tests/keycloak/test_keycloak_users.py`).
- `nexus/api/app/tasks_api.py:421-447` - `/logs`, `/results/approve`, `/results/block` raise `NotImplementedException` with no test. `/cancel` has one (`test_pull_requests_and_tasks.py:787`). Add the same 501 test for the other three, or remove the routes.
- `nexus/ui/src/pages/` - 12 page folders, 1 has tests (`projects/projects.test.tsx`, 3 tests). 14 tests in total across the UI. No tests for login, tasks, triggers, results, secrets, datasets, providers or `src/api/client.ts` / `auth.ts`.
- `k8s/federated-node/tests/failures/` - `missing_aws_necessary_secrets.yaml` and `missing_azure_necessary_secrets_test.yaml` are in a subfolder; the runner uses `CMD ["."]` (`build/helm-unittest/Dockerfile:8`), so helm-unittest's default `tests/*_test.yaml` glob does not pick them up, and the first one also lacks the `_test` suffix. The "missing secrets must fail" checks do not run.
  Fix: move both to `tests/` with a `_test.yaml` suffix, or pass `-f 'tests/**/*_test.yaml'`.

## 3. Flakiness risks

- `nexus/api/tests/test_git_tokens.py:102` - `8 * 60 < claims["exp"] - time.time() <= 9 * 60` depends on the wall clock between minting and asserting. Freeze time or compare against `iat`.
- `nexus/api/tests/test_stateful_rules.py:72` - `CLOCK_START` is `utcnow()` at import; `test_pull_requests_and_tasks.py:205`, `test_trigger_repositories_and_resources.py:428-429` and `test_git_providers.py:214` also build times from `utcnow()`. Not seen failing; they are naive-UTC and import-time dependent.
- `nexus/api/tests/test_live_client_integration.py:67-73` - real uvicorn server on a thread with a `while not server.started: sleep(0.05)` loop and no timeout; a failed start hangs the run. Only matters once the module actually runs (see section 1).

## 4. Skipped / xfail / stale

- Covered in section 1: one module-level skip and two `skipif`s that are always true, one `xfail` that hides a failure.
- `k8s/federated-node/tests/__snapshot__/` is empty and no suite uses `matchSnapshot`. Delete the folder.
- No `assert True`, no `@pytest.mark.skip`, no `it.skip` / `it.todo` found in the reviewed suites.

## 5. Duplicated fixtures / setup

- `dagster/app/tests/test_ingest_job.py:24` and `dagster/app/tests/test_pr_ingest_sensor.py:27` - `fake_git_api` is the same helper twice (the first adds a `files` argument). Move to `dagster/app/tests/conftest.py`.
- `backend_api` fixture defined separately in `dagster/app/tests/test_git_api_factory.py:18`, `test_results_delivery.py:100`, `test_task_run_status_sensor.py:75`, although `conftest.py:166` already has `make_backend_api_mock`. Same in fncli: `test_config.py:191`, `test_repository.py:16`, `test_secret.py:27`.
- `session` / `api` fixtures duplicated between `dagster/app/tests/test_backend.py:18-23` and `dagster/fncli/tests/test_backend.py:35-40` (fncli copies the client on purpose, so this one may be intended).
- The repo-root / `CONTRACT` path is computed four times in `nexus/api/tests` and three of the four are wrong (section 1).

## Not covered

- `dagster/fncli/tests/` beyond the automated no-assert scan (clean) and fixture names; mock patch paths there were not checked.
- Mock patch paths in general (wrong import path) - not checked in any suite.
- Dagster sensors against their tests beyond "each sensor has a test file" and the run-status file; error paths in launcher, reconcile, delivery, pull-request sync not compared.
- Per-route 409 / auth / project-scoping coverage for projects, results, healthcheck and trigger-repository routes: only counted (409 and `other_project` appear in most files), not matched route by route.
- Helm suites' content (only discovery was checked); UI test content.
- Ordering dependence and shared mutable fixtures in `nexus/api/tests/conftest.py`.
