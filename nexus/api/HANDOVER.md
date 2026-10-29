# nexus/api handover

Read this, then `CONTRACT.md`, then `PLAN.md`. Branch `nexus/api`, worktree
`fn-worktrees/nexus/api`. Commit and push to `origin nexus/api` (plain push) after each milestone.

## Done
- `nexus/api/app` copied from `nexus/api/app` without `extras/` (except `catalogue.py` and `dictionary.py`,
  which `POST /global/datasets` writes), without `registries/whitelisted_images/dar/admin` routers and
  without `helpers/container_registries.py` (only the registry code used it).
- Skeleton:
  - `app/helpers/base_model.py`: `scoped_session` keyed by the `request_scope` contextvar, `Base.query`,
    `db.session`/`db.Model` kept so the copied models and helpers are unchanged, `paginate()` + `Page`.
  - `app/middleware.py`: `SessionMiddleware` (pure ASGI; sets the scope, removes the session after; a
    request where a scope is already set joins it, which is how tests share the fixture session),
    `JsonObjectBodyMiddleware` (non-object JSON body -> 400).
  - `app/errors.py`: the error table from PLAN.md; validation errors are 400; a path param that fails
    validation (non-integer id) is 404.
  - `app/helpers/wrappers.py`: `get_caller` (`Caller(token, user_id, is_admin, is_system, kc_client)`,
    cached per request by FastAPI), `require_scope(scope)`, `system_only`. `@audit` is gone.
  - `app/helpers/query_filters.py`: `QueryFilters` dependency; `arg_get(filters, name, default, type)`.
  - `app/helpers/soft_delete.py`: `delete_global(resource, project_resources, force)`.
  - `app/helpers/keycloak.py`: `get_token_from_headers(headers)`.
  - `app/helpers/exceptions.py`: `LogAndException` is a plain `Exception` (no werkzeug).
  - `app/__init__.py`: `create_app()`, every router registered up front (`module.router`, plus
    `tasks_api.all_router`). Agents never touch it.
- Ported routers: `main`, `secrets_api`, `projects_api` (lead); Wave A: `project_trigger_repositories_api`,
  `tasks_api`, `results_api`, `results_repositories_api`, `datasets_api`, `git_providers_api`,
  `healthcheck_api` (each agent reported its own test files green). `trigger_repositories_api` (it also fixed 3 test bugs copied from nexus-api tests in
  `test_pull_requests_and_tasks.py`: missing `system_headers` fixture args). Wave B (`users_api`, `dagster_api`): one agent running at the last update.
- Tests: all converted mechanically (`response.json` -> `response.json()`, `query_string=` -> `params=`,
  `data=` -> `content=`). `conftest.py` `client` is a `TestClient` subclass that also takes `json=` on
  get/delete. Registry/audit/DAR tests and fixtures removed.
- `CONTRACT.md`, `dump_openapi.py` -> `openapi.json` (only ported routers are in it).
- `run_local_tests.sh` (fast, venv + postgres container, per-caller DB) and `run_tests.sh` (docker compose).

## In progress / Next
1. Fan-out: Wave A done (all eight routers committed). Wave B running at the last update.
2. Helm/Tilt/Dockerfile: see "Status of Helm/Tilt" at the bottom.
3. Spec path diff: done, clean. `openapi.json` regenerated with every router. Against
   `nexus/api/app/static/openapi.json` (minus registries/whitelisted_images/dar/audit) the only
   missing paths are ones the previous backend didn't have either (the hand-written spec drifted:
   `/task_requests*`, `/global/datasets/by-name/*`, `*/revoke`), plus `PATCH /delivery-secret`, which is
   in `admin_api` (out of scope with it). nexus adds `/ready_check` and `.../tasks/{id}/retry`, both real.
   Whole-suite run: see "Test status".
4. `tests/test_live_client_integration.py` serves the app with uvicorn in a thread (done), but it
   skips locally: the Dagster client modules need the `dagster` package, which isn't in
   `/tmp/nexus-venv`. To run it: `pip install dagster` into the venv (match `dagster/` deps), then
   `./run_local_tests.sh tests/test_live_client_integration.py`. Not run yet.
5. After the port: the `nexus-api` / `nexus-system` two-deployment step (PLAN.md).

## Test status (last run)
- `tests/test_projects_api.py`: all pass except the ones needing trigger repositories
  (`test_assigning_a_trigger_repository_to_an_enabled_project_is_201` and 3 fixture errors) -> green after Wave A.
- `tests/test_secrets_quarantine.py`: the secret-only tests pass; the rest need datasets / trigger /
  results repositories / healthcheck routers -> recheck after Wave A.
- `tests/test_smoke.py`: needs trigger repositories and users.

## How to resume
```bash
python3 -m venv /tmp/nexus-venv && /tmp/nexus-venv/bin/pip install fastapi uvicorn httpx python-multipart \
  "sqlalchemy~=2.0.49" psycopg2-binary "kubernetes~=33.1.0" joserfc "pyjwt~=2.10.1" pymssql requests \
  cryptography "pydantic~=2.0" pydantic-settings pytest pytest-mock pytest-cov responses pytest-responses \
  hypothesis python-dotenv
docker run -d --name nexus-test-db -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=test_app \
  -p 55432:5432 postgres:17-alpine
cd nexus/api && NEXUS_TEST_DB=nexus_mine ./run_local_tests.sh tests/test_projects_api.py
```
Never run e2e tests. Run only the test files for what you changed, foreground, with a timeout.

## How to run
**Local uvicorn** (against the dev cluster's Postgres and Keycloak, forwarded by Tilt on 5432 and 8080):
```bash
cd nexus/api
export PGHOST=localhost PGPORT=5432 NEXUS_DB_USER=<backend db user> NEXUS_DB_PASSWORD=<pw> NEXUS_DB_NAME=<db>
export KEYCLOAK_URL=http://localhost:8080 KEYCLOAK_REALM=FederatedNode KEYCLOAK_CLIENT=global \
  KEYCLOAK_SECRET=<global client secret> DEFAULT_NAMESPACE=<ns> TASK_NAMESPACE=<tasks ns> PUBLIC_URL=localhost:5004
/tmp/nexus-venv/bin/uvicorn --factory app:create_app --reload --port 5004
```
Same env vars as the backend pod (`kubectl get cm backend-configmap keycloak-config -o yaml`). Docs at
`http://localhost:5004/docs`, spec at `/openapi.json`. nexus-api owns the database migrations and runs `alembic upgrade head` on startup.

**Unit tests**: see "How to resume" (`run_local_tests.sh`, venv + `nexus-test-db` container). CI-style:
`./run_tests.sh` (docker compose, as nexus-api's).

**Tilt**: `NEXUS_API_ENABLED=true tilt up` with the chart deployed with nexus on (next item). Builds
`localhost:5001/nexus-api-fn`, runs `uvicorn --reload`, syncs `nexus/api/app`, forwards `localhost:5004`.

**Helm values** to turn nexus-api on (in `dev.values.yaml` or `--set`):
```yaml
nexus:
  image: localhost:5001/nexus-api-fn   # dev only, so Tilt can swap it; default ghcr.io/aridhia-open-source/nexus_api
  api:
    enabled: true                   # pathPrefix /nexus on the backend host (traefik.enabled), replicas 1
```
Then `make deploy` (the user's call; the dev cluster wasn't touched here). Check with
`helm template t k8s/federated-node -f <values>` (needs `charts/` deps).
Merge note: `nexus/ui` also adds a `nexus:` block (`nexus.ui.*`) to `values.yaml`; merge the two blocks
when the branches meet (`nexus.image`/`nexus.tag`/`nexus.port` are the API's; consider moving them under
`nexus.api` then).

**Pointing the UI (nexus/ui) at nexus**:
- Vite dev server (5173, UI at `http://localhost:5173/nexus-ui/`):
  `cd nexus/ui && VITE_NEXUS_API_URL=http://localhost:5004 npm run dev` (5004 = nexus via Tilt or local
  uvicorn; the UI's default 5001 is the local registry, so always set it).
- In the cluster: `nexus.ui.backendUri: http://nexus-api.<namespace>.svc:5000` (the nexus-api Service).
- Types: switch the UI's `gen:api` to `nexus/api/openapi.json` (regenerate with `python dump_openapi.py`).

## Gotchas
- Decisions made by Wave A agents, to review:
  - `tasks_api`/`models/task.py`: `Task.validate(data, user_token)` takes the token; the image whitelist
    and "image exists on the registry" checks are removed (their models are out of scope), only the image
    format check is left (`Task.validate_image_format`). So a task with a missing image is now a 201,
    where nexus-api gave 404. `ENABLE_IMAGE_WHITELIST` in `helpers/const.py` is unused.
  - `tasks_api.does_user_own_task(task, caller)` uses the caller (no own Keycloak); `results_api` imports it.
  - `datasets_api` POST/PATCH keep `body: dict` + `.parse(body)`: the credential/project_id rejections
    need the raw body (`DatasetRequest` ignores extras), and the `Invalid dataset: ...` message stays.
  - Typed-body routes (git providers, repositories) answer a bad body with 400 before a 404 for a missing id.
  - `healthcheck_api` has a local `_trigger_resource` in place of importing `_assignment` from
    `project_trigger_repositories_api` (it was a stub then); can be swapped back now.
- `run_local_tests.sh`: if `createdb` says the database already exists, rerun (race with a parallel run).
- Tests are cross-cutting: one test file often hits several routers, so a failure can be another,
  unported router (a 404 `{"error": "Not Found"}` on its route). Don't chase those.
- The session is per request in production, but a test and its requests share one session (scope
  `"test"` set by the `client` fixture). Don't add `session.remove()` anywhere else.
- `raise_server_exceptions=False` on the test client: a bug in a handler is a 500 and its traceback is
  logged (`ERROR main`), not raised in the test.
- Keycloak patch paths in `conftest.py` are unchanged: `app.helpers.wrappers.Keycloak`,
  `app.main.Keycloak`, `app.users_api.Keycloak`, `app.tasks_api.Keycloak`, `app.models.task.Keycloak`.
  The stubs of `users_api` and `tasks_api` import `Keycloak` so those patches resolve; keep that import.
- `app/models/task.py:105` calls `Keycloak.get_token_from_headers()` with no args (the previous backend
  read the request context). The tasks agent must pass the token down (`caller.token`) instead.
- `tests/tasks/test_resource_validators.py` and `tests/tasks/test_task_from_spec.py` import
  `tests.fixtures.azure_cr_fixtures` (deleted, registry code). The tasks agent drops that import and
  the `registry_client` / `cr_client` fixture args.
- `delete_global` and `?force=`: handlers take `force: bool = False` and pass it.
- `pyproject.toml` / `requirements*.txt` are set up for FastAPI and uvicorn.

## How to port a router (checklist)
Pattern to copy: `app/projects_api.py` (pagination, filters, `caller.is_admin`, dynamic 201/200) and
`app/secrets_api.py` (router-level auth plus an admin-only write). Source: `nexus/api/app/<name>.py`.
Edit only `app/<name>.py` and, if a test needs a client-API fix, the test files you own.

1. Imports: `from fastapi import APIRouter, Body, Depends, Response`; drop any the previous backend imports; `from
   app.helpers.wrappers import Caller, get_caller, require_scope, system_only`.
2. `bp = Blueprint(..., url_prefix=P)` -> `router = APIRouter(prefix=P, tags=["<name>"])`. If every route
   has the same `@auth(scope=S)` (or a `@bp.before_request @auth`), put
   `dependencies=[Depends(require_scope(S))]` on the router; otherwise per route
   `dependencies=[Depends(require_scope(S))]` on the decorator. Several modules have more than one
   blueprint (tasks: `bp` and `all_bp`); keep the names `router` and `all_router`, which
   `app/__init__.py` already includes. Drop `@audit`.
3. `@bp.route('/<int:x>/y', methods=['GET'])` -> `@router.get('/{x}/y', response_model=SomeDTO)`
   with `x: int` in the signature. Collection routes keep both `''` and `'/'` decorators.
4. Status: declare `status_code=HTTPStatus.CREATED` / `NO_CONTENT` on the decorator and return the DTO
   (not `.dump()`, not a tuple). When the code picks 201 or 200 at run time, take `response: Response`
   and set `response.status_code`. DELETE 204 returns nothing.
5. Body: an existing request DTO becomes a typed param (`req: ProjectRequest`), dropping `.parse()`.
   Hand-validated `request.json or {}` becomes `body: dict = Body(default_factory=dict)` with the same
   checks. A body that is a list stays `body: list = Body()`... only if nexus-api took a list.
6. `g.caller_is_admin` / `g.caller_is_system` -> `caller: Caller = Depends(get_caller)` and
   `caller.is_admin` / `caller.is_system`. Keycloak token from headers -> `caller.token`.
7. `@system_only` -> add `Depends(system_only)` to the route's `dependencies`, after its
   `require_scope`. System-only routes are in PLAN.md "Two deployments".
8. Query params: `request.args.copy()` -> `filters: QueryFilters = Depends()` and `filters.copy()`;
   `arg_get('page', 1, type=int)` -> `arg_get(filters, 'page', 1, type=int)`; `?force=` ->
   `force: bool = False`; other single params -> typed query params with the same defaults.
9. Paged lists keep returning `page_of(...)` (a dict), no `response_model`.
10. Run your test files: `NEXUS_TEST_DB=nexus_<name> ./run_local_tests.sh tests/<files>`. Fix your
    router, not the tests; edit a test only for a test-client difference.

Before/after for one handler (`projects_api.py`):
```python
# before (previous backend)
@bp.route('/<int:project_id>/datasets/<int:dataset_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_dataset(project_id: int, dataset_id: int):
    resource = _dataset_resource(project_id, dataset_id)
    body = request.json or {}
    ...
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")
    ...
    return ProjectDatasetDTO.from_model(resource).dump(), HTTPStatus.OK

# after (FastAPI; can_admin_dataset is on the router)
@router.patch('/{project_id}/datasets/{dataset_id}', response_model=ProjectDatasetDTO)
def patch_project_dataset(project_id: int, dataset_id: int, body: dict = Body(default_factory=dict),
                          caller: Caller = Depends(get_caller)):
    resource = _dataset_resource(project_id, dataset_id)
    ...
    if "revoked" in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")
    ...
    return ProjectDatasetDTO.from_model(resource)
```

## Fan-out instructions (one Sonnet agent per router)
Agents edit files only; the lead commits after each wave. No git commands, no branch switching,
no e2e, no cluster. Each agent: port `nexus/api/app/<name>.py` into `nexus/api/app/<name>.py` with the
checklist above, run its test files with its own `NEXUS_TEST_DB`, report what passes, what fails and
why (another router's 404 is fine). Favour working code over coverage: don't write new tests, don't
loop on test runs or chase flaky/minor failures; note them and stop.

Wave A (parallel):
| router module | test files to run |
|---|---|
| `trigger_repositories_api` | `test_trigger_repositories_and_resources.py`, `test_pull_requests_and_tasks.py` (PR ingest parts) |
| `project_trigger_repositories_api` | `test_trigger_repositories_and_resources.py`, `test_triggers.py` |
| `tasks_api` | `tasks/`, `test_task_launch.py`, `test_all_tasks_list.py`, `test_pagination_and_filters.py` |
| `results_api` | `test_results_and_delivery.py` |
| `results_repositories_api` | `test_global_resources.py` (results parts) |
| `datasets_api` | `test_global_resources.py` (dataset parts), `test_create_refuses_revoked.py` |
| `git_providers_api` | `test_git_providers.py` |
| `healthcheck_api` | `test_healthchecks_all.py` |

Wave B: `users_api` (`keycloak/test_keycloak_users.py`, `test_smoke.py`), `dagster_api` (grep tests for
`/dagster`). Then `test_system_user_routes.py`, `test_stateful_rules.py`, `test_e2e_flow.py`,
`test_live_client_integration.py` (see Next 4) as a whole-suite pass (Haiku).

## Status of Helm/Tilt
- Done: `nexus/api/Dockerfile` (uvicorn `--factory app:create_app` on 5000, with alembic init container),
  `pyproject.toml` (fastapi, uvicorn, python-multipart, httpx, alembic),
  `requirements.txt` / `requirements-dev.txt` recompiled with hashes.
- Chart: `k8s/federated-node/templates/nexus-api-{deployment,service,configmap,http-route,roles}.yaml`
  (replaces previous backend templates). Values under `nexus.api.*`. Runs at `/` on the host (no `/nexus` prefix).
  Own service account `nexus-api` bound to the secrets ClusterRole. Reuses `keycloak-config`; 
  `nexus-api-configmap` sets `NEXUS_ROLE=api` (for the two-deployment step). Init container runs `alembic upgrade head`.
- Checked: `helm lint` and `helm template` render clean.
- Tilt: `tilt up` builds `localhost:5001/nexus-api-fn` with `uvicorn --reload`,
  syncs `nexus/api/app`, forwards `5000:5000`.
  For Tilt to swap the image, dev values must set `nexus.image: localhost:5001/nexus-api-fn`.
