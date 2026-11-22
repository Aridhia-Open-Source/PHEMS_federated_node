"""
Entrypoint for nexus-api: uvicorn --factory app:create_app.
Every router is registered here up front; a router module owns its routes and nothing else.
Deny by default: every router needs an admin node role (or Dagster), except the ones in OPEN_ROUTERS.
"""
import logging

from fastapi import Depends, FastAPI
from fastapi_pagination import add_pagination

from app import (
    main, datasets_api, tasks_api, projects_api, users_api, trigger_repositories_api,
    project_trigger_repositories_api, secrets_api, git_providers_api, results_repositories_api, results_api,
    dagster_api, healthcheck_api,
)
from app.errors import register_error_handlers
from app.helpers.wrappers import ADMIN_ROLES, DAGSTER, require_role
from app.middleware import JsonObjectBodyMiddleware, SessionMiddleware, TrailingSlashMiddleware

logging.basicConfig(level=logging.WARN)
logger = logging.getLogger('main')
logger.setLevel(logging.INFO)

# The only routers reachable without an admin role. Keep this list short.
OPEN_ROUTERS = (
    main.router,  # /, /ready_check, /health_check, /login, /refresh_token: probes and getting a token
    users_api.reset_password_router,  # PUT /global/users/reset-password: a new user swaps their temp password
)


def create_app() -> FastAPI:
    app = FastAPI(title="Federated Node", redirect_slashes=False)
    register_error_handlers(app)
    # The last added runs first: the session scope wraps everything
    app.add_middleware(JsonObjectBodyMiddleware)
    app.add_middleware(SessionMiddleware)
    app.add_middleware(TrailingSlashMiddleware)

    for router in (
        main.router, projects_api.router, datasets_api.router, tasks_api.router, results_api.router,
        users_api.reset_password_router, users_api.router, trigger_repositories_api.router,
        project_trigger_repositories_api.router, secrets_api.router, git_providers_api.router,
        results_repositories_api.router, dagster_api.router, healthcheck_api.router, tasks_api.all_router,
    ):
        admin_only = router not in OPEN_ROUTERS
        app.include_router(router, dependencies=[Depends(require_role(*ADMIN_ROLES, DAGSTER))] if admin_only else None)
    # After the routers: it adds the page and size parameters to every route whose response_model is a Page
    add_pagination(app)
    return app
