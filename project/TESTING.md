# Testing

What each kind of test in this repository covers, what it does not, and how to run it. There are three kinds:

| Kind | Where | Needs | Proves |
|---|---|---|---|
| Webserver tests (route tests, a model-based test) | [webserver/tests/](../webserver/tests/) | A Postgres; Keycloak and Kubernetes are mocked | The webserver's rules and routes, one request at a time |
| Dagster app tests and fncli tests | [dagster/app/tests/](../dagster/app/tests/), [dagster/fncli/tests/](../dagster/fncli/tests/) | Nothing running; the webserver, git host and Dagster instance are mocked | Each sensor, job and command does what the webserver's answer says |
| End-to-end suites | [dagster/fncli/tests/e2e/](../dagster/fncli/tests/e2e/) | The live dev cluster (`kind-fn`) | That the real pieces work together |

A by-hand plan for a deployed node, which takes over where these stop, is in [QA/README.md](QA/README.md).

Read first: the decisions are in [decisions/README.md](decisions/README.md) and win over this file. Checks that have never run on a cluster are listed [below](#checks-that-have-never-run-on-a-cluster).

## Webserver tests

Black-box tests of the Flask app: an HTTP request through the test client, then assertions on status codes and response bodies only. Each test gets a fresh database. Keycloak and the Kubernetes client are mocked, so the admin and System tokens of the fixtures are not real logins.

### How to run

- The normal route is [webserver/run_tests.sh](../webserver/run_tests.sh). It uses Docker Compose, builds the test image, starts a Postgres and runs pytest (`-x -v`). The first argument `ci` runs the CI variant; the second is the pytest argument (default `.`). It sets the database and Keycloak environment variables itself.
- For quicker runs of a single file, start a Postgres, set the same variables with `PGHOST` and `PGPORT` pointing at it, and run pytest from `webserver/` in a virtualenv built from `requirements-dev.txt`:

  ```bash
  docker run -d --name fn-routes-test-db -e POSTGRES_DB=test_app -e POSTGRES_USER=admin \
    -e POSTGRES_PASSWORD=test_app -p 127.0.0.1:55432:5432 postgres:17-alpine
  cd webserver
  python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
  .venv/bin/pytest tests/<file>.py -q -p no:cacheprovider --no-cov -W ignore
  ```

  `--no-cov` skips the coverage that `setup.cfg` turns on.
- Two tests that compare a response with a sample from the Dagster tree skip themselves when `dagster/` is not beside `webserver/` (the CI container mounts only the webserver). `test_live_client_integration.py` skips for the same reason.

### What they cover, by area

Counts are `def test_` lines; a parametrised test counts once.

| Area | Files | What is covered |
|---|---|---|
| GlobalResources | `test_global_resources.py` (36), `test_git_providers.py` (18) | Create, patch, delete and 404/409/400 rules of datasets, Secrets, TriggerRepositories, ResultsRepositories and GitProviders; names are normalised; values are never returned; non-admin writes refused; a disabled GitProvider makes its repositories inactive |
| Projects and project resources | `test_projects_api.py` (21), `test_trigger_repositories_and_resources.py` (25) | Project CRUD, `enabled`, `backfill`, soft delete cascade; project resource lifecycle per kind (PUT 201/200, PATCH, DELETE); `revoked` admin only; the active filters; two projects on one repository; switching back on skips the gap |
| `enabled` and `revoked` | the two files above, `test_git_providers.py`, `test_create_refuses_revoked.py` (5), `test_results_and_delivery.py` | Flags at project, project resource, GlobalResource and GitProvider level; revoke never changes `enabled`; `revoked` is never accepted on create; a revoked or deleted ProjectResource gives a final `REVOKED` result |
| Pull requests and fan-out | `test_pull_requests_and_tasks.py` (52), `tests/helpers/pull_requests.py` | Ingest is idempotent and capped at 100; the match rule (`base_branch`, `.json` added under `watch_dir`); the two cursors; skipped gap; backfill; one merge commit on two base branches; creating a task from a pull request; task status routes |
| Triggers and tasks from a spec | `test_triggers.py` (9), `tasks/test_task_from_spec.py` (23), `tasks/test_patch_task.py` (7), `tasks/test_resource_validators.py` (6), `test_dtos_task_spec.py` (15) | Trigger models and `set_state`; a valid spec makes a PENDING task (from the API or a pull request), a bad spec keeps a REJECTED trigger with a cause; dataset override and default; a disabled or revoked project refuses a task; the task is pinned at creation; CPU and memory validators |
| Task pinning and launch | `test_task_config.py` (37), `test_task_launch.py` (12) | The snapshot and its diff; a changed `target_dir` or dataset makes the task stale; the order of causes (revoked, changed, dataset not active, Secret disabled); `POST .../launch` fails or launches and is safe to repeat |
| Results and delivery records | `test_results_and_delivery.py` (50) | Results resource rules (`target_dir`, one per project, project disabled to assign, cross-project loops); result creation order (`REVOKED`, `STALE`, switched off and held `FAILED`); forward-only step; filters |
| Secrets | `test_secrets_quarantine.py` (14), `test_global_resources.py` | A disabled Secret's value moves to a quarantine namespace and back; delete rules; enabling on a disabled Secret is a 409 (Kubernetes client is an in-memory store) |
| State tables | `test_state_rules.py` (5) | Every (current, new) pair of the trigger, task and result step tables |
| List routes and shapes | `test_pagination_and_filters.py` (17), `test_all_tasks_list.py` (12), `test_dtos.py` (18) | Pagination, filters, response field names and date formats (the Dagster models depend on them) |
| Healthchecks | `test_healthchecks_all.py` (16) | Per-GlobalResource, per-project and global healthchecks; a failed check is a 200 with a status in the body; `secret_missing` |
| System user | `test_system_user_routes.py` (9) | The Dagster System user writes what Dagster and fncli manage and can never revoke |
| Helpers | `test_git_uri.py`, `test_kubernetes_*`, `test_containers_*_registries_helper.py`, `keycloak/` | URI parsing, Kubernetes name and secret helpers, registry helpers, the Keycloak helper layer. The registries and Keycloak parts are mostly not part of the beta pipeline ([Authorization detached from DAR, Keycloak and whitelisted images](decisions/0017-authorization-detached-from-dar-and-keycloak.md)) |
| In-process flow | `test_e2e_flow.py` (1) | One route-level run through the whole API (secret, provider, repositories, dataset, project resources, enable, ingest, task). The name says e2e, but it is the Flask test client with mocks, not a live end-to-end test |
| Real clients | `test_live_client_integration.py` (9) | The fncli backend client and the Dagster `BackendAPI` against the real Flask app over HTTP, no Kubernetes |

[webserver/tests/TEST_PLAN.md](../webserver/tests/TEST_PLAN.md) is superseded. It was the plan for the first set of route tests, which were later merged into the files above, and it still names an `IGNORED` state that no longer exists. Keep it only for its fixture list and its traps (assign first, then ingest; assigning a results repository needs the project disabled; the mocked Keycloak lets a non-admin token through every scope except `revoked`).

### The Hypothesis stateful test

`webserver/tests/test_stateful_rules.py` (collected as `TestTriggerResourceRules`) is a model-based test. Hypothesis builds random sequences of actions against the real API, and after every action compares the API's state with a small model of the rules.

- Actions: merge a pull request (matching or not), ingest, ingest into an inactive repository (refused), evaluate one trigger, progress a task, set `enabled` or `revoked` on the project resource, the global trigger repository and the project, enable a project with or without `backfill`, a refused `backfill`.
- Invariants checked each time: the project's triggers, the stored pull requests, the tasks, the project resource's `active` and all the flags match the model.
- Rules it encodes: [revoke-and-enabled.md](../docs/architecture/revoke-and-enabled.md), [Enabled, revoked and soft delete](decisions/0008-enabled-revoked-and-soft-delete.md) and [Pull requests stored once per repository, fanned out to project resources, with cursors](decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md) (the cursor, fan-out, skipped gap and backfill).
- Run: it needs `hypothesis` (in `requirements-dev.txt`) and the usual test database, and is collected like any other test file. The default is a quick smoke run (about 45 s). `STATEFUL_DEEP=1` runs the deep search (about 7 minutes); run that before relying on the file.
- It cannot show: anything about more than one project or more than one project resource; Secrets, datasets, results, pinning, GitProvider flags; Dagster, sensors, time or restarts. It is also a model written from the same rules: it finds the code disagreeing with the rules, not a wrong rule.

### What the webserver tests cannot show

- Anything in Dagster, Gitea, GitHub, Kubernetes or Keycloak: all are mocked or absent. Real logins, token lifetimes, roles and scopes are not tested (a non-admin is refused only for `revoked`).
- Timing and ordering between components (sensor ticks, a run finishing between two ticks, two writers racing).
- That the Dagster side and the webserver agree on a wire shape, except where a contract sample is compared (see below).

## Dagster app tests

`dagster/app/tests/`. Dagster, the webserver and the git hosts are mocked; a sensor or job is called with a built context and the calls it makes are asserted.

### How to run

- `cd dagster && ./run_tests.sh [ci] [pytest args]` (Docker Compose, the test image is built from the local Dagster image), or `make tests_dagster` from the repo root (the `ci` variant). `pytest_args` default to `.`; the paths in `dagster/pyproject.toml` are `app/tests` and `fncli/tests`, so the fncli tests run with them. The end-to-end tests are skipped unless `--e2e` is given.
- `dagster/app/tests/test_enum_drift.py` needs the whole checkout (it parses the webserver source) and skips in the test image. Run it from the repo root: `pytest dagster/app/tests/test_enum_drift.py`.
- The end-to-end README runs pytest from the repo root with `dagster/.venv/bin/python -m pytest dagster ...`.

### What they cover, by area

| Area | Files | What is covered |
|---|---|---|
| Ingest | `test_pr_ingest_sensor.py` (13), `test_ingest_job.py` (9) | Polls only pollable repositories; one run per repository with new pull requests; the run key (cursor and slot); batches of at most 100, oldest first; a failing repository does not stop the others; the tick fails only when nothing launched |
| Evaluate | `test_pr_evaluate_sensor.py` (9), `test_evaluate_job.py` (9), `test_pr_parser.py` (5) | Enabled projects and active project resources only; a spec file that is missing, several, or invalid makes a REJECTED trigger; a 409 is skipped |
| Launcher | `test_task_launcher.py` (17) | One call per PENDING task; the webserver's `fail` or `launch` is followed; the run key `task/<id>/<attempt>`; an error leaves the task PENDING; disabled project's tasks wait |
| Task status | `test_task_run_status_sensor.py` (10), `test_task_reconcile_sensor.py` (16) | The run-status mapping; the reconcile sensor patches from the run's current status, skips a 409, ignores a disabled project, makes no second patch |
| Delivery | `test_results_delivery.py` (34), `test_github_parity.py` | The branch layout, the `results.zip` size cap, a retry resumes from the step reached, a held `FAILED` result counts an attempt and waits for the retry sensor, the retry sensor stops at the maximum attempts, a 404 or 409 is final, a hung git command times out, the token stays out of the command line |
| Results pull request sync | `test_results_pull_request_sync.py` (16) | MERGED and CLOSED are recorded; a deleted pull request is skipped; a 409 is skipped; a provider error fails the sync |
| Sensor plumbing and settings | `test_sensor_base.py` (9), `test_definitions.py` (11), `test_config.py` (18), `test_utils.py` (28), `test_backend.py` (43) | Run keys and slots, in-flight skip, sensors registered STOPPED, settings defaults (interval 30 s, retry slot 60 s, 5 delivery attempts, 10 MiB cap), the HTTP client's token refresh and retry on 401/403/429, backend client calls |
| Git providers and Secrets | `test_gitea.py` (19), `test_github.py` (15), `test_git_api_factory.py` (5), `test_git_pr_ops.py` (10), `test_git_uri.py`, `test_secrets.py` (9) | Both providers give the same results and errors; the repository's own token is read each time; a disabled Secret is never read |
| Task pod and run config | `test_pipes.py` (32), `test_run_config.py` | The task pod's settings (no service account token, task namespace, security context, dataset environment, per-run artifact path) |
| Models and drift | `test_models.py` (25), `test_enum_drift.py` (1) | Wire models parse webserver payloads and keep unknown fields; Dagster's enums carry the webserver's values |

### Contract samples between the webserver and Dagster

`dagster/app/tests/contract/launch_response.json` and `tasks_response.json` are samples of two webserver responses. The Dagster tests (`test_task_launcher.py`) parse them into Dagster's models. The webserver tests (`test_task_launch.py`, `test_all_tasks_list.py`) compare the real response's keys with the sample. When the real response gains or loses a key, the webserver test fails, so the two sides move together. They check the shape (keys), not the values, and only for these two responses.

### What the Dagster tests cannot show

- A real Dagster instance with real runs, a real daemon, restarts, or sensor ticks in the Dagster UI. The reconcile sensor was tested against a fake instance and one real instance, never a live Dagster with real runs ([checks that have never run on a cluster](#checks-that-have-never-run-on-a-cluster)).
- A real git host's behaviour (rate limits, paging, errors); Gitea and GitHub responses are canned.
- That the task pod runs, that artifacts exist on the volume, that the run image honours its settings.
- The rules themselves: Dagster holds none ([Responsibility: the webserver owns the record and the rules; Dagster carries out decisions](decisions/0021-webserver-owns-the-record-and-the-rules.md)); these tests only check that it follows the answer.

## fncli tests

`dagster/fncli/tests/` (run with the Dagster tests; see above). They check the command line tool, with the backend, Gitea, Dagster and Kubernetes mocked.

| Area | Files | What is covered |
|---|---|---|
| Command set and settings | `test_cli.py` (7), `test_config.py` (13) | The expected commands are registered; the settings classes (the Gitea address and in-cluster URL translation, empty values rejected, Secret labels) |
| Setup and pull request commands | `test_pr.py` (20), `test_dataset.py`, `test_backend.py` (18), `test_git_uri.py` | The file each `--kind` of pull request commits; branch names; what `--watch` prints; backend find-or-create and assign calls; URI translation |
| State commands | `test_state.py` (16) | `resource-set --revoked` logs in as the first Keycloak user; everything else uses the Dagster System user |
| Sensors and verify | `test_sensor.py` (6), `test_verify.py` (16) | `all` covers the twelve sensors once each; the order a group starts and stops in; what `verify-project` and `verify-repo` report |
| Simulation | `test_simulation.py` (10) | The plan and checker of the multi-provider simulation on built states, with no cluster. The simulation itself has not been run ([dagster/fncli/README.md](../dagster/fncli/README.md)) |

They cannot show that a command works against the real cluster; that is what the end-to-end suites are for.

## Other checks

- `webserver/integration_tests/` (run with `webserver/run_integration_tests.sh`): the Keycloak initialiser against a real Keycloak over several runs on the same database (first install, migrations run once, operator config survives, secret and password rotation). It is about deployment, not the pipeline. Check before relying on it for a given release.
- `scripts/e2e_shared_resources.sh` and `scripts/e2e_check.py`: an older shell run of the shared-GlobalResources flow on the dev cluster. The pytest end-to-end suites below are the maintained version; check before using it.

## End-to-end tests

`dagster/fncli/tests/e2e/`. They drive the real stack (webserver, Keycloak, Postgres, Dagster and Gitea on the `kind-fn` cluster) through fncli, one fncli command or one expected state per test, in order, on one project. The first failure stops the run and prints the last project snapshot. Details: [dagster/fncli/tests/e2e/README.md](../dagster/fncli/tests/e2e/README.md).

### What they need

- The local dev cluster only (`kubectl` context `kind-fn`, Tilt green). Never a shared or production cluster, and never `make teardown` to run them. Work from the worktree that owns the cluster.
- The backend (`:5000`), Gitea (`:4000`), Dagster (`:3000`) and Keycloak (`:8080`) answering on localhost (the Tilt port-forwards).
- All sensors already running: `fncli start-sensor --group all`. The suites do not start or stop them.
- `.dev.env` in the repo root, with the `TEST_*` values from `.dev.env.example`.
- An admin login: revoking is admin only, so fncli logs in as the first Keycloak user, whose credentials `deploy.sh` stores in the `keycloak-first-user` secret from `KEYCLOAK_FIRST_USER_EMAIL` and `KEYCLOAK_FIRST_USER_PASSWORD` in `.dev.env`. (The end-to-end README calls these `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD`; the code reads the secret. Check.) The failure suite checks the login first and fails with the cause.
- Images built from the branch under test (`make deploy`), including `pypipes-fn`: the failing-task group needs the run image to honour `PYPIPES_EXIT_CODE`.

### How to run

From the repo root:

```bash
dagster/.venv/bin/python -m pytest dagster --e2e success -v -x -p no:cacheprovider
dagster/.venv/bin/python -m pytest dagster --e2e failure -v -x -p no:cacheprovider
```

`--e2e` alone runs both, success first, then failure. The project is cleared at the start of each run and left in place afterwards; `E2E_TEARDOWN=1` tears it down at the end. `E2E_FAST_SENSORS=1` sets the sensor interval to 1 s for the run (it restarts the code server, which stops the sensors, so start them again first). `E2E_TASK_TIMEOUT` (default 600 s) bounds a task that has to start. A plain `pytest` skips all of them.

### Order

The success suite runs first, then the failure suite. Within a suite the tests run in file order.

**Success suite** (`test_happy_path.py`): clear leftovers, `setup-project` steps, `verify-project`; then branch, commit a watched spec, open and merge the pull request; the pull request is ingested (UNKNOWN) and YIELDED with a task; the task is created, QUEUED, RUNNING, SUCCESS; a result exists, reaches PUSHED and OPENED; the results pull request is merged with `merge-results-pr`; the result is MERGED; `verify-project` and `verify-repo --tail 1` pass; teardown (only with `E2E_TEARDOWN=1`).

**Failure suite** (`test_failure_paths.py`): the admin login check; clear leftovers (including the second project) and set up; the project starts empty; then these groups, in this order:

1. An invalid spec is rejected, no task.
2. A pull request outside the watched directory creates no trigger.
3. A pull request merged while the trigger resource is revoked never gets a trigger (un-revoking does not replay it).
4. A second project on the same repository (both get a task; revoking the second project's resource means only the first gets the next one; the second project is torn down).
5. A lost token fails clearly, then recovers (nothing ingested; the ingest sensor shows an auth error; the healthcheck fails; a fresh token and `verify-git-secret`; the missed pull request is then processed; the healthcheck is ok).
6. A failing task stays failed (FAILED, no result).
7. A pull request merged while the project is revoked is stored and gets no task (restoring does not replay it).
8. A pull request merged while the trigger resource is switched off gets no task.
9. A pull request merged while the GlobalResource (the trigger repository) is switched off gets no task.
10. A pull request merged while the GlobalResource is revoked gets no task.
11. A pull request merged while the trigger repository's Secret is switched off gets no task (switching the Secret on does not switch the repository on).
12. A pull request merged while the project is disabled gets a task when it is enabled with backfill.
13. Work in flight: a results resource switched off before delivery. The task still launches and runs; the result is held `FAILED`; nothing is delivered while the project resource is off; switched on, the retry sensor delivers it.
14. Teardown (only with `E2E_TEARDOWN=1`).

The "nothing happens" checks wait five sensor ticks.

### What the suites cover

- Success: one pull request in the Gitea trigger repository through ingest, evaluate, a task, a run and delivery to a merged results pull request, and that `verify-project` and `verify-repo` pass.
- Failure: the groups above. Together they check the trigger side of `enabled`, `revoked`, the skipped gap and backfill, a lost token, a failing task, two projects on one repository, and one case of work in flight.

### Not covered by any end-to-end test for now

This list is copied from the end-to-end README and the failure suite's docstring. The scenarios that stop and start sensors were removed and will be looked at again later; the reconcile sensor is expected to make up for sensors being down. The rules are in [revoke-and-enabled.md](../docs/architecture/revoke-and-enabled.md) ("May a waiting task launch?" and "May a finished task's result be delivered?"). Only the webserver and Dagster unit tests cover revoking a result that is already held, and retrying tasks is not covered (on hold until after the beta).

- `failure`: restarting the ingest sensor does not duplicate pull requests or tasks, also after a trigger resource was revoked and un-revoked.
- `failure`: a task whose results resource's `target_dir` changes before it launches fails, and its cause names the change (the pinned configuration changed).
- `failure`: sensors that were all stopped while a pull request was merged catch up when started: the pull request gets one trigger and one task, and no task stays `PENDING`.
- `failure`: a results resource revoked after the task succeeded and before its delivery leaves the result `REVOKED` and `FAILED`, never delivered, and un-revoking the project resource delivers nothing.
- `failure`: a results resource's `target_dir` changed after the task succeeded and before its delivery leaves the result `STALE` and `FAILED`, never delivered, and restoring the `target_dir` delivers nothing.
- `failure`: a dataset resource revoked while the task is `PENDING` makes the task fail at launch with a cause that starts "revoked: " and names the dataset, with no result.
- `failure`: a global dataset switched off while the task is `PENDING` makes the task fail at launch with a cause saying the dataset is not active and naming it, with no result.

Also not covered, from the end-to-end README: the Gitea mirror, authentication and normal-user permissions. Beyond that list, by reading the groups above: GitHub as the provider (Gitea only), GitProvider flags, the dataset side of `enabled` and `revoked` apart from the two removed behaviours above, a results resource or results repository revoked rather than switched off, and combinations of switches. These are covered by unit tests only, where at all.

Probes the end-to-end README lists as worth a manual check, not a pass or fail:

- More than 100 merged pull requests behind one cursor: stop ingest, merge 101 watched pull requests, start ingest. Ingest posts them in batches of 100, so all are stored.
- A revoked Secret resource: `fncli resource-set secret --revoked true`, then open a pull request. Revoked Secret resources are not checked when a token is read.

### Checks that have never run on a cluster

These have not been run against a cluster. When one is run and the result recorded, remove it from this list.

- The failure suite (`pytest dagster --e2e failure`), including the group where a results resource is switched off and the result is delivered once the project resource is switched back on. Two assumptions in it are unchecked: a task can be created and launched while its results resource is switched off, and the watched task uses the project's default dataset.
- The success and failure suites with the launch endpoint and the reconcile sensor in place.
- `dagster/app/tests/test_enum_drift.py`, from a full checkout: it skips when `webserver/` is not beside `dagster/`.
- The reconcile sensor catching up: stop the sensors, let a task run to the end, then start them. The reconcile sensor should bring the task to its final status. It finds the run by its `trigger`, `task_id` and `attempt` tags. It was tested against a fake instance and one real instance, never a live Dagster with real runs; check that its ticks show in the Dagster UI.

Treat the failure suite as written but not proven on a cluster until a run is recorded.

## Which kind of test proves which kind of rule

| Kind of rule | Webserver tests | Dagster / fncli tests | End-to-end | Left for the by-hand plan |
|---|---|---|---|---|
| A route's status codes, validation, admin-only, 404 and 409 | Yes, the main proof | No | Only a few 409s through `--expect` | Real roles and logins |
| `enabled` and `revoked` at every level, the skipped gap, backfill | Yes (route tests; the stateful test for the project, one project resource and one global repository) | The sensors skip what the list filters leave out | Trigger side only: project, project resource, GlobalResource, Secret | GitProvider, dataset, results side, combinations, timing |
| Task pinning (a task fails or its result is stale) | Yes (`test_task_config.py`, `test_task_launch.py`) | The launcher follows the answer | None | The whole behaviour on a live node (the cases were removed from the end-to-end suites) |
| State tables (forward only, final states, 409) | Yes (`test_state_rules.py` and the route tests) | Sensors treat a 409 as "already moved on" | Indirectly (states reached in order) | A late write racing a final state |
| Pull requests stored once, fan-out, cursors | Yes | Ingest batches, run keys | One repository, one or two projects | Several projects, concurrency, more than 100 pull requests |
| Secrets and quarantine | Yes (Kubernetes mocked) | A disabled Secret is not read | Disabled trigger Secret only | The real store, the quarantine namespace, rotation |
| Sensor behaviour (ticks, run keys, retry slots) | No | Yes (mocked instance) | The sensors run, but are never stopped or restarted | Restarts, catch-up, stopped sensors, order of start |
| Delivery (layout, size cap, resume, retry) | Result records only | Yes (mocked git) | One delivery to Gitea; one held and retried | Failures mid-delivery, large results, GitHub |
| Wire shapes between the webserver and Dagster | `test_dtos.py` | Wire models parse | Whole stack | Only the two sampled responses are compared |
| Authentication, roles, normal users | Mocked | Mocked | Admin login only | Out of scope for the beta |

### How the three fit together

1. The webserver tests prove the rules, because the webserver owns them. Everything else asks the webserver and acts.
2. The Dagster and fncli tests prove the doers follow the webserver's answer: they mock the answer and check the call that follows. They hold no copy of the rules to test.
3. The contract samples and the enum-drift test tie the two sides together at the wire.
4. The end-to-end suites prove the real pieces are connected: sensors, webserver, Gitea and the task run on one cluster. Each group is a path through rules the unit tests already prove one at a time.
5. What none of them does well is time: sensors stopped or restarted, a change while a task is pending or running, services going down mid-flow, concurrent merges. Those cases are in [QA/sensors-restarts-and-catch-up.md](QA/sensors-restarts-and-catch-up.md) and [QA/failures-mid-flow-and-limits.md](QA/failures-mid-flow-and-limits.md), and [QA/README.md](QA/README.md) ranks the whole plan by risk.
