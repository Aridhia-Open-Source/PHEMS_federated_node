"""
Auth dependencies. require_scope replaces the previous backend's @auth(scope), system_only its @system_only.
A route (or a router, through dependencies=[...]) depends on require_scope(scope); a handler that needs
who is calling takes `caller: Caller = Depends(get_caller)`, which FastAPI resolves once per request.
"""
import logging
from dataclasses import dataclass

from fastapi import Depends, Request

from app.helpers.const import OWNER_GROUPS
from app.helpers.exceptions import AuthenticationError, UnauthorizedError
from app.clients.keycloak import Keycloak
from app.models.user import User

logger = logging.getLogger('wrappers')
logger.setLevel(logging.INFO)


@dataclass
class Caller:
    token: str
    user_id: str
    is_admin: bool
    is_system: bool
    kc_client: Keycloak
    # The caller's realm roles and Keycloak groups, from the token
    groups: frozenset[str]
    # The caller's row in users, created or refreshed on this call (ADR 0036)
    user: User

    @property
    def owner_group(self) -> str | None:
        """The first of OWNER_GROUPS the caller is in: the group that locks the records it writes."""
        return owner_group_of(self.groups)


def token_groups(token_info: dict) -> frozenset[str]:
    """The realm roles and the Keycloak groups (when the token has a groups claim) a decoded token carries."""
    roles = token_info.get("realm_access", {}).get("roles", [])
    groups = [g.lstrip("/") for g in token_info.get("groups", [])]
    return frozenset([*roles, *groups])


def owner_group_of(groups: frozenset[str]) -> str | None:
    return next((g for g in OWNER_GROUPS if g in groups), None)


def get_caller(request: Request) -> Caller:
    """The decoded caller, cached per request by FastAPI's dependency cache."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise AuthenticationError("Token not provided")

    kc_client = Keycloak()
    token_info = kc_client.decode_token(token)
    user = kc_client.get_user_by_username(token_info['username'])
    groups = token_groups(token_info)

    # TODO(DAR): DAR checking is disconnected, as in the previous backend. Every caller takes the plain path.
    return Caller(
        token=token,
        user_id=user["id"],
        is_admin=kc_client.is_user_admin(token),
        is_system=kc_client.is_system_user(token),
        kc_client=kc_client,
        groups=groups,
        user=User.seen(user["id"], user["username"]),
    )


def require_scope(scope: str):
    def _require_scope(caller: Caller = Depends(get_caller)) -> Caller:
        if not caller.kc_client.is_token_valid(caller.token, scope, 'endpoints', 'refresh_token'):
            raise UnauthorizedError("Token is not valid, or the user has not enough permissions.")
        return caller
    return _require_scope


def system_only(caller: Caller = Depends(get_caller)) -> Caller:
    """
    Only the system user (Dagster) may call it, whatever scope the caller holds. Admins hold the scopes
    of the state-machine routes to manage datasets. Goes next to the route's require_scope.
    """
    if not caller.is_system:
        raise UnauthorizedError("Only the system user can change this state.")
    return caller

