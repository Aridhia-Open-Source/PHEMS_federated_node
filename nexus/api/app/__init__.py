"""
Entrypoint for nexus-api: uvicorn --factory app:create_app.
Every router is registered here up front; a router module owns its routes and nothing else.
"""
import logging

from fastapi import FastAPI

from app import (
    main, datasets_api, tasks_api, projects_api, users_api, trigger_repositories_api,
    project_trigger_repositories_api, secrets_api, git_providers_api, results_repositories_api, results_api,
    dagster_api, healthcheck_api,
)
from app.errors import register_error_handlers
from app.middleware import JsonObjectBodyMiddleware, SessionMiddleware

logging.basicConfig(level=logging.WARN)
logger = logging.getLogger('main')
logger.setLevel(logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(title="Federated Node", redirect_slashes=False)
    register_error_handlers(app)
    # The last added runs first: the session scope wraps everything
    app.add_middleware(JsonObjectBodyMiddleware)
    app.add_middleware(SessionMiddleware)

    for module in (
        main, projects_api, datasets_api, tasks_api, results_api, users_api, trigger_repositories_api,
        project_trigger_repositories_api, secrets_api, git_providers_api, results_repositories_api, dagster_api,
        healthcheck_api,
    ):
        app.include_router(module.router)
    app.include_router(tasks_api.all_router)
    return app
