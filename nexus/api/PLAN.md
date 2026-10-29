# nexus/api: FastAPI replacement for the previous backend

`nexus` is a working name. It may be renamed later, so keep the name in as few places as you can (the directory, the image, the Helm template names and the Tilt resource).

## Context
- **Before:** the previous backend was a separate app, with about 105 live handlers.
- **Now:** nexus is a FastAPI version that replaces it. It provides a generated, accurate OpenAPI spec, which the React admin UI (branch `nexus/ui`, `nexus/ui/PLAN.md`) is typed from.
- **The previous `nexus-api/` directory is deleted** and nexus/api takes its place in the architecture.

### Rules
- **Same wire contract:** the paths, methods, body shapes, `{"error": ...}` error bodies (plus `"details"` when present), 400 on validation errors and the pagination keys (`items/page/per_page/total/pages`, or `tasks` for the tasks list) all stay the same. Dagster and fncli then switch to nexus with one env var (`NEXUS_API_URL`).
- **Database and migrations:** nexus uses the same Postgres database as before. nexus-api owns the alembic migrations and runs `alembic upgrade head` in an init container on startup.
- **Out of scope:** everything under `nexus/api/app/models/extras/` (audit, catalogue, dar, dictionary, registry, whitelisted_image) and the routes on them: `registries_api`, `whitelisted_images_api`, `dar_api` and `admin_api` (audit). Don't port `@audit`.
- **No new features or DTOs during the port.** Copy the existing patterns.
- **Base:** `dagster-develop`. Work on `nexus/api`. Don't merge into `dagster-develop` or open a PR unless asked.

## Working arrangement
- **Handover:** `nexus/api/HANDOVER.md`, with sections for done / in progress / next / gotchas / how to resume.
  - Update it after every milestone (one router ported, one test file green) and before you stop. Commit it and push it.
  - A fresh session reads `HANDOVER.md`, then `CONTRACT.md`, then this file.
- **Contract with the UI:** `nexus/api/CONTRACT.md` records the error shape, the auth flow (`POST /login`, `Authorization: Bearer`), the pagination keys and where the generated spec lives.
  - Update it whenever any of these is settled or changes.
  - The UI team reads it from `origin/nexus/api`. Their requests are in `nexus/ui/HANDOVER.md` under "Needs from nexus" on `origin/nexus/ui`, so check that when you start.
- **Agents:** one strong agent (Opus) does the skeleton, auth, error handling and the example routers. Sonnet agents then port the remaining routers in parallel, one router (plus its tests) each.
- **Tests:** run only the test files for what you changed, in the foreground with a timeout. **Never run e2e tests** (`pytest --e2e`, `dagster/fncli/tests/e2e`). If a run crashes or fails in a way you can't fix, write it in the handover and stop.
- **Code style:** top-level imports only (tests excepted). No defensive code or fallback defaults: fail fast. Keep comments sparse, like the surrounding code.

## Shape
- `nexus/api/` is a new directory (its sibling `nexus/ui/` is the React UI): `nexus/api/app`, `nexus/api/tests`, `nexus/api/Dockerfile`, `nexus/api/pyproject.toml` and `requirements*.txt`.
- **Start by copying** `nexus/api/app` (models, DTOs, helpers, without `extras/`) and the matching `nexus/api/tests`, then convert them. The DTOs in `nexus/api/app/dtos/` are already Pydantic v2 (`DTO` with `from_attributes`, `dump()`).
- **Server:** uvicorn on port 5000. Handlers are sync `def`, because Keycloak, k8s and requests are all blocking.
- **Probes:** keep `/ready_check` and `/health_check`.

## Request lifecycle

### 1. Middleware
These are async and run in order:
- Set the request scope id for the DB session.
- Reject JSON bodies that are not objects, the same as `nexus/api/app/__init__.py` `before_request`.
- On the way out, remove the session.

### 2. DB session (drop the previous ORM layer)
- **Session:** a plain SQLAlchemy `scoped_session`, with `scopefunc` reading a contextvar that the middleware sets.
  - Don't set the scope in a sync dependency. Sync dependencies and handlers each run in their own threadpool call with a copied context, so the handler would not see it.
- **Model queries:** `Base.query = session.query_property()` keeps `Model.query` working across the models.
- **Pagination:** a `paginate(query, page, per_page)` helper replaces `.paginate`. Adapt `dtos/base.py:page_of` to it.
- **Errors:** `get_db` rolls back on an exception.
- **First test you write:** a dependency and its handler share one session, and two concurrent requests get different sessions.

### 3. Auth
- **`require_scope`:** `helpers/wrappers.py:auth(scope)` becomes `require_scope(scope)`, a dependency that returns `Caller(token, user_id, is_admin)`. `g.caller_is_admin` becomes `caller.is_admin`.
- **Router-level auth:** blueprint-wide `@bp.before_request @auth(...)` becomes a router-level `dependencies=[Depends(require_scope(...))]`.
- **Admin-only writes:** these add `require_scope("can_do_admin")`.
- **Unauthenticated routes stay unauthenticated:** `/login`, the health and ready routes, and `PUT /global/users/reset-password`.
- **Keycloak:** reuse `helpers/keycloak.py` as is, and cache the decoded user per request. Keep the manual `Bearer ` parsing so the 401 body keeps its shape.
- **System-user-only writes:** `Caller` also carries `is_system` (from `keycloak.py:is_system_user`). A `system_only` dependency gives a 403 to any caller who isn't the system user. It goes on the state-machine writes (listed under "Two deployments" below).
  - The human admin actions stay `can_admin_task`: task retry and cancel, and results approve and block.

### 4. Validation and DTOs
- **Request DTOs** (`ProjectRequest`, `DatasetRequest`, ...) become typed body params, and **response DTOs** become `response_model=`.
- **Hand-validated bodies:** handlers that hand-validate `request.json` use an existing request DTO where there is one. Where there isn't, they use `dict = Body()` plus their existing checks.
- **Request values the helpers used to read:** `?force=` (`helpers/soft_delete.py`) and page and per_page (`helpers/base_model.py`) are passed in explicitly.
- **Filters:** the dynamic `field__gte=` filters (`helpers/query_filters.py`) come through a `QueryFilters` dependency that reads `request.query_params`.
- **Status codes:** handlers return DTOs and declare `status_code=` on the decorator, instead of returning `(body, status)` tuples.

### 5. Errors (`app/errors.py`)

| Exception | Response |
|---|---|
| `LogAndException` and subclasses | its code, `{"error": description, "details"?: extra_fields}` |
| Starlette `HTTPException` (404, 405) | `{"error"}` |
| `RequestValidationError` | 400 `{"error"}` (matches today's `.parse()` 400s) |
| `IntegrityError` | rollback, 409 `{"error": "Record already exists"}` |
| any other `Exception` | rollback, log, 500 `{"error": "Internal Error"}` |

### 6. Routing
`redirect_slashes=False`, and register both `""` and `"/"` on collection routes, the same as the previous backend. Behind Traefik a 307 redirect can point at `http://` and break the clients.

### 7. OpenAPI
Served at `/openapi.json`, with docs at `/docs`. A test (or a `make` target) dumps the spec to `nexus/api/openapi.json` and commits it, so the UI can generate types from it.

## Helm and Tilt
- **Helm:**
  - `k8s/federated-node/templates/nexus-api-{deployment,service,http-route,configmap,roles}.yaml`, replacing the previous `backend-*.yaml`.
  - nexus-api runs at `/` on the host (no `/nexus` prefix).
  - An init container runs `alembic upgrade head` before the app starts.
  - Check it with `helm lint` / `helm template` if they are available.
- **Tilt:** a `docker_build_with_restart` entry for nexus-api that runs `uvicorn --reload`, plus a port-forward on 5000.

## Two deployments: `nexus-api` and `nexus-system` (after the port)
**Decision:** one codebase and one image, deployed twice. **Don't** split the routers or the code by deployment. The routers stay grouped by resource.

| Deployment | Who calls it | Exposure |
|---|---|---|
| `nexus-api` | the UI, admins, fncli, users | Traefik http route, as planned above |
| `nexus-system` | Dagster only (its `NEXUS_API_URL` points here) | ClusterIP only, no http route. A NetworkPolicy allows traffic only from the Dagster namespace. |

- **Why:** Dagster polls every 30s, so that load stays off the admin side, and each deployment scales and restarts on its own. For security, the state-machine routes are not reachable from outside the cluster at all.
- **`NEXUS_ROLE` env var** (`api` or `system`, set by Helm, required with no default):
  - **On `api`:** the system-only routes are not mounted, or they return 404.
  - **On `system`:** every route requires the system user. It's a router-level dependency on the whole app, so there's no per-route bookkeeping.
- **The system-only routes:** each gets one `system_only` dependency or tag:

| Route | What it is |
|---|---|
| `POST /global/repositories/triggers/{id}/pull_requests` | pull request ingest |
| `PATCH /projects/{id}/repositories/triggers/{rid}/pull_requests/{n}` | pull request state |
| `POST /projects/{id}/repositories/triggers/{rid}/pull_requests/{n}/task` | creates a task from a pull request |
| `PATCH /projects/{id}/tasks/{tid}` and `POST .../launch` | task state and launch |
| `POST /projects/{id}/results` and `PATCH /projects/{id}/results/{rid}` | result state |

- **Reads Dagster also uses** (projects, trigger and results repos, task config and trigger) stay on both deployments, untouched.
- **Helm:**
  - A second Deployment and Service (`nexus-system-*`) from the same templates, with a values toggle `nexus.system.enabled`.
  - Point Dagster's `NEXUS_API_URL` at it when it's enabled.
- **Not in the first cut:** do the port first. This step is Helm plus one dependency.

## Steps

### Opus: skeleton
1. Copy the code and tests, then write `CONTRACT.md` and `HANDOVER.md`.
2. Build the app factory, middleware, session, `paginate`, auth dependencies and error handlers.
3. Add one stub router module per remaining `*_api.py`, all registered up front, so later agents never touch shared files.
4. Convert the tests:
   - The `client` fixture becomes a Starlette `TestClient`.
   - `response.json` becomes `response.json()`.
   - Update the Keycloak patch import paths in `conftest.py`.
   - `test_smoke.py` reads `app.routes`.
   - The live-client test serves with uvicorn in a thread.
5. Port the example routers, with their tests green:
   - `main` (login, health)
   - `secrets` (router-level auth plus an admin-only write)
   - `projects` (pagination, filters, `caller.is_admin`)
6. Add the Dockerfile, Helm templates and Tilt entry.
7. Write a "how to port a router" checklist in `HANDOVER.md`, with the before/after for one handler.

### Sonnet: fan-out
Run in parallel. Each agent ports one router plus its tests.
- **Wave A**, the routes Dagster and the fncli demo use:
  - `trigger_repositories`
  - `project_trigger_repositories`
  - `tasks`
  - `results`
  - `results_repositories`
  - `datasets`
  - `git_providers`
  - `healthcheck`
- **Wave B:** `users`, and the `dagster` sensors proxy.

### Last
- Run the whole nexus unit suite once.
- Diff the generated spec's paths against `nexus/api/app/static/openapi.json` (minus the out-of-scope routes) to catch missed routes.

### After the port
- Do the two-deployment step (`nexus-api` and `nexus-system`, above) as its own change.

## Verification
- The per-router tests pass, then the full nexus unit suite.
- `tests/test_live_client_integration.py` passes (the real Dagster and fncli clients against nexus).
- The spec path diff is clean.
- `helm template` renders with `nexus.api.enabled=true`.
- Tilt and the cluster run are checked locally by the user, not here.
