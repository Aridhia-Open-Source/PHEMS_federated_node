# nexus/api handover

Read this, then `CONTRACT.md`, then `PLAN.md`. Branch `nexus/api`, worktree
`fn-worktrees/nexus/api`. Commit and push to `origin nexus/api` (plain push) after each milestone.

## Done
- `nexus/api/app` copied from `webserver/app` without `extras/` (except `catalogue.py` and `dictionary.py`,
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
  - `app/helpers/soft_delete.py`: `delete_global(resource, links, force)`.
  - `app/helpers/keycloak.py`: `get_token_from_headers(headers)`.
  - `app/helpers/exceptions.py`: `LogAndException` is a plain `Exception` (no werkzeug).
  - `app/__init__.py`: `create_app()`, every router registered up front (`module.router`, plus
    `tasks_api.all_router`). Agents never touch it.
- Ported routers: `main`, `secrets_api`, `projects_api`.
- Tests: all converted mechanically (`response.json` -> `response.json()`, `query_string=` -> `params=`,
  `data=` -> `content=`). `conftest.py` `client` is a `TestClient` subclass that also takes `json=` on
  get/delete. Registry/audit/DAR tests and fixtures removed.
- `CONTRACT.md`, `dump_openapi.py` -> `openapi.json` (only ported routers are in it).
- `run_local_tests.sh` (fast, venv + postgres container, per-caller DB) and `run_tests.sh` (docker
  compose, as the webserver's).

## In progress / Next
1. Fan-out (below): Wave A then Wave B.
2. Helm/Tilt/Dockerfile: see "Status of Helm/Tilt" at the bottom.
3. Last: whole nexus unit suite once; `python dump_openapi.py`; diff its paths against
   `webserver/app/static/openapi.json` minus registries/whitelisted_images/dar/audit.
4. `tests/test_live_client_integration.py`: switch the werkzeug `make_server` to uvicorn in a thread
   (`uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=0))`, wait for `server.started`,
   read the port from `server.servers[0].sockets[0].getsockname()[1]`). Not done.
5. After the port: the `nexus-api` / `nexus-system` two-deployment step (PLAN.md).

## Test status (last run)
- `tests/test_projects_api.py`: all pass except the ones needing trigger repositories
  (`test_a_trigger_link_to_an_enabled_project_is_201` and 3 fixture errors) -> green after Wave A.
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

## Gotchas
- Tests are cross-cutting: one test file often hits several routers, so a failure can be another,
  unported router (a 404 `{"error": "Not Found"}` on its route). Don't chase those.
- The session is per request in production, but a test and its requests share one session (scope
  `"test"` set by the `client` fixture). Don't add `session.remove()` anywhere else.
- `raise_server_exceptions=False` on the test client: a bug in a handler is a 500 and its traceback is
  logged (`ERROR main`), not raised in the test.
- Keycloak patch paths in `conftest.py` are unchanged: `app.helpers.wrappers.Keycloak`,
  `app.main.Keycloak`, `app.users_api.Keycloak`, `app.tasks_api.Keycloak`, `app.models.task.Keycloak`.
  The stubs of `users_api` and `tasks_api` import `Keycloak` so those patches resolve; keep that import.
- `app/models/task.py:105` calls `Keycloak.get_token_from_headers()` with no args (it read Flask's
  request). The tasks agent must pass the token down (`caller.token`) instead.
- `tests/tasks/test_resource_validators.py` and `tests/tasks/test_task_from_spec.py` import
  `tests.fixtures.azure_cr_fixtures` (deleted, registry code). The tasks agent drops that import and
  the `registry_client` / `cr_client` fixture args.
- `delete_global` and `?force=`: handlers take `force: bool = False` and pass it.
- `pyproject.toml` / `requirements*.txt` still list the webserver's deps (Flask); see Helm/Tilt status.

## How to port a router (checklist)
Pattern to copy: `app/projects_api.py` (pagination, filters, `caller.is_admin`, dynamic 201/200) and
`app/secrets_api.py` (router-level auth plus an admin-only write). Source: `webserver/app/<name>.py`.
Edit only `app/<name>.py` and, if a test needs a client-API fix, the test files you own.

1. Imports: `from fastapi import APIRouter, Body, Depends, Response`; drop flask; `from
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
   checks. A body that is a list stays `body: list = Body()`... only if the webserver took a list.
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
# before (Flask)
@bp.route('/<int:project_id>/datasets/<int:dataset_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_dataset(project_id: int, dataset_id: int):
    link = _dataset_link(project_id, dataset_id)
    body = request.json or {}
    ...
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")
    ...
    return ProjectDatasetDTO.from_model(link).dump(), HTTPStatus.OK

# after (FastAPI; can_admin_dataset is on the router)
@router.patch('/{project_id}/datasets/{dataset_id}', response_model=ProjectDatasetDTO)
def patch_project_dataset(project_id: int, dataset_id: int, body: dict = Body(default_factory=dict),
                          caller: Caller = Depends(get_caller)):
    link = _dataset_link(project_id, dataset_id)
    ...
    if "revoked" in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")
    ...
    return ProjectDatasetDTO.from_model(link)
```

## Fan-out instructions (one Sonnet agent per router)
Agents edit files only; the lead commits after each wave. No git commands, no branch switching,
no e2e, no cluster. Each agent: port `webserver/app/<name>.py` into `nexus/api/app/<name>.py` with the
checklist above, run its test files with its own `NEXUS_TEST_DB`, report what passes, what fails and
why (another router's 404 is fine). Favour working code over coverage: don't write new tests, don't
loop on test runs or chase flaky/minor failures; note them and stop.

Wave A (parallel):
| router module | test files to run |
|---|---|
| `trigger_repositories_api` | `test_trigger_repositories_and_links.py`, `test_pull_requests_and_tasks.py` (PR ingest parts) |
| `project_trigger_repositories_api` | `test_trigger_repositories_and_links.py`, `test_triggers.py` |
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
- Done: `nexus/api/Dockerfile` (uvicorn `--factory app:create_app` on 5000, no alembic),
  `pyproject.toml` (Flask/alembic/waitress out; fastapi, uvicorn, python-multipart, httpx in),
  `requirements.txt` / `requirements-dev.txt` recompiled with hashes.
- Chart: `k8s/federated-node/templates/nexus-api-{deployment,service,configmap,http-route,roles}.yaml`
  behind `nexus.api.enabled` (default false). Values under `nexus:` (image, tag, port, `api.replicas`,
  `api.pathPrefix: /nexus`). Same host as the backend under `/nexus`, prefix stripped by a URLRewrite
  filter. Own service account `nexus-api` bound to the backend's secrets ClusterRole. Reuses
  `backend-configmap` + `keycloak-config`; `nexus-api-configmap` sets `NEXUS_ROLE=api` (not read by
  the code yet; the two-deployment step uses it).
- Checked: `helm lint` and `helm template --set nexus.api.enabled=true` (with `traefik.enabled=true`
  for the route) render clean. The chart needs its `charts/` deps: I copied them from the main
  checkout into a temp copy of the chart to render.
- Tilt: `NEXUS_API_ENABLED=true tilt up` builds `localhost:5001/nexus-api` with `uvicorn --reload`,
  syncs `nexus/api/app`, forwards `5002:5000` (5001 is the local registry).
  `scripts/tilt_manifests.py` takes the extra deployment. Not run here (no cluster).
  For Tilt to swap the image, dev values must set `nexus.image: localhost:5001/nexus-api` (the backend
  does the same for `webserver-fn`) and `nexus.api.enabled: true`.
