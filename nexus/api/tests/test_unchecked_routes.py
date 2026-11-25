"""
Deny by default (ADR 0037): every route declares an Access check, and create_app refuses to start without one, or
with an unchecked route that has no role gate of its own. The routes that skip the record check are listed here, so
a new one shows up in review.
"""
import inspect

import pytest
from fastapi import APIRouter, Depends

import app as app_module
from app import create_app, routers
from app.rules.authz import ADMIN_UNCHECKED, Access, Action, Global, api_routes, routes_without_access
from app.models.node_role import ADMIN_ROLES, NodeRole
from app.models.dataset import Dataset

# Routes with Access(action=UNCHECKED), and why
UNCHECKED_ROUTES = {
    # probes and getting a token
    "GET /", "GET /ready_check", "GET /health_check", "POST /login", "POST /refresh_token",
    # a new user swaps their temporary password, with no token
    "PUT /global/users/reset-password",
    # Keycloak accounts, not records; admin roles only
    "GET /global/users", "POST /global/users",
    # Dagster's sensors, not records; reads allow Dagster and admin roles, writes allow admin roles only
    "GET /dagster/sensors", "GET /dagster/sensors/{name}", "PATCH /dagster/sensors", "PATCH /dagster/sensors/{name}",
    # every global record's health at once; admin roles only
    "GET /global/healthcheck",
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


def test_the_unchecked_routes_are_the_known_ones():
    routes = {
        f"{method} {route.path}"
        for route in api_routes(routers()) if _unchecked(route.dependant)
        for method in route.methods if method in ("GET", "POST", "PUT", "PATCH", "DELETE")
    }
    assert routes == UNCHECKED_ROUTES


def test_dagster_sensor_reads_allow_the_dagster_role():
    from app.rules.authz import DAGSTER_READ_UNCHECKED

    role_gate = next(
        dependency.dependency for dependency in DAGSTER_READ_UNCHECKED
        if getattr(dependency.dependency, "__name__", "") == "_require_role"
    )
    roles = set(inspect.getclosurevars(role_gate).nonlocals["roles"])

    assert roles == set(ADMIN_ROLES) | {NodeRole.DAGSTER}


def test_a_write_route_without_access_stops_the_app(mocker):
    router = APIRouter()

    @router.post("/forgotten")
    def forgotten():
        """A write route nobody checked."""

    mocker.patch.object(app_module, "routers", lambda: (router,))
    with pytest.raises(RuntimeError, match="POST /forgotten"):
        create_app()


def test_a_read_route_without_access_stops_the_app(mocker):
    router = APIRouter()

    @router.get("/forgotten")
    def forgotten():
        """A read route nobody checked."""

    mocker.patch.object(app_module, "routers", lambda: (router,))
    with pytest.raises(RuntimeError, match="GET /forgotten"):
        create_app()


def test_an_unchecked_route_without_a_role_gate_stops_the_app(mocker):
    """Every node role passes the routers, so an unchecked route would be open to Users."""
    router = APIRouter()

    @router.get("/open", dependencies=[Depends(Access(action=Action.UNCHECKED))])
    def open_route():
        """Unchecked, and nothing gates it."""

    @router.get("/gated", dependencies=ADMIN_UNCHECKED)
    def gated_route():
        """Unchecked, gated by the admin roles."""

    mocker.patch.object(app_module, "routers", lambda: (router,))
    with pytest.raises(RuntimeError, match="role gate: GET /open$"):
        create_app()


def test_every_route_is_checked():
    assert not routes_without_access(routers())


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
