"""
Deny by default (ADR 0037): every write route declares an Access check, and create_app refuses to start without
one. The routes that skip the record check are listed here, so a new one shows up in review.
"""
import pytest
from fastapi import APIRouter

import app as app_module
from app import create_app, routers
from app.rules.authz import Access, Action, Global, api_routes, routes_without_access
from app.models.dataset import Dataset

# Write routes with Access(action=UNCHECKED), and why
UNCHECKED_WRITE_ROUTES = {
    # probes and getting a token
    "POST /login", "POST /refresh_token",
    # a new user swaps their temporary password, with no token
    "PUT /global/users/reset-password",
    # Keycloak accounts, not records; admin roles only
    "POST /global/users",
    # Dagster's sensors, not records; admin roles only
    "PATCH /dagster/sensors", "PATCH /dagster/sensors/{name}",
    # Dagster's pipeline state writes and token mints (SYSTEM_ONLY)
    "POST /global/repositories/triggers/{repo_id}/pull_requests",
    "POST /global/repositories/triggers/{repo_id}/token",
    "POST /global/repositories/results/{repo_id}/token",
    "PATCH /projects/{project_id}/repositories/triggers/{repo_id}/pull_requests/{number}",
    "POST /projects/{project_id}/repositories/triggers/{repo_id}/pull_requests/{number}/task",
    "POST /projects/{project_id}/results",
    "PATCH /projects/{project_id}/results/{result_id}",
    "PATCH /projects/{project_id}/tasks/{task_id}",
    "POST /projects/{project_id}/tasks/{task_id}/launch",
    "POST /projects/{project_id}/tasks/{task_id}/runs/{run_id}/resources",
}


def _unchecked(dependant) -> bool:
    return any(
        (isinstance(dep.call, Access) and dep.call.action == Action.UNCHECKED) or _unchecked(dep)
        for dep in dependant.dependencies
    )


def test_the_unchecked_write_routes_are_the_known_ones():
    routes = {
        f"{method} {route.path}"
        for route in api_routes(routers()) if _unchecked(route.dependant)
        for method in route.methods if method in ("POST", "PUT", "PATCH", "DELETE")
    }
    assert routes == UNCHECKED_WRITE_ROUTES


def test_a_write_route_without_access_stops_the_app(mocker):
    router = APIRouter()

    @router.post("/forgotten")
    def forgotten():
        """A write route nobody checked."""

    mocker.patch.object(app_module, "routers", lambda: (router,))
    with pytest.raises(RuntimeError, match="POST /forgotten"):
        create_app()


def test_a_read_route_without_access_is_not_refused_yet():
    """#688 adds GET to CHECKED_METHODS."""
    assert all(not entry.startswith("GET ") for entry in routes_without_access(routers()))


@pytest.mark.parametrize("kwargs", [
    {"action": Action.WRITE},
    {"model": Dataset, "action": Action.UNCHECKED},
], ids=["checked without a model", "unchecked with a model"])
def test_access_misuse_raises_at_import(kwargs):
    with pytest.raises(TypeError):
        Access(**kwargs)


def test_access_takes_keyword_arguments_only():
    with pytest.raises(TypeError):
        Access(Global, Action.WRITE)  # pylint: disable=too-many-function-args
