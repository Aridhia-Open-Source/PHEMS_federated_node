"""
Auth dependencies (ADR 0035). nexus-api checks Keycloak access tokens itself, against the realm's published
keys, so a normal request makes no Keycloak call.

A handler that needs who is calling takes `caller: Caller = Depends(get_caller)`, which FastAPI resolves once
per request. Routers depend on require_role(...); the routes only Dagster may call add system_only.
"""
from fastapi import Depends, Request

from app.dtos.caller import Caller
from app.clients.access_token import access_tokens
from app.helpers.exceptions import AuthenticationError, UnauthorizedError
from app.models.node_role import NodeRole


def get_caller(request: Request) -> Caller:
    """The verified caller, cached per request by FastAPI's dependency cache."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise AuthenticationError("Token not provided")

    return Caller.from_claims(access_tokens.claims(token))


def require_role(*roles: NodeRole):
    def _require_role(caller: Caller = Depends(get_caller)) -> Caller:
        if caller.role not in roles:
            raise UnauthorizedError("The user has not enough permissions.")
        return caller
    return _require_role


def system_only(caller: Caller = Depends(get_caller)) -> Caller:
    """Only Dagster may call it, whatever else the router allows. Goes next to the router's require_role."""
    if caller.role != NodeRole.DAGSTER:
        raise UnauthorizedError("Only the system user can change this state.")
    return caller
