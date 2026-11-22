"""
Auth dependencies (ADR 0036). nexus-api checks Keycloak access tokens itself, against the realm's published
keys, so a normal request makes no Keycloak call.

A handler that needs who is calling takes `caller: Caller = Depends(get_caller)`, which FastAPI resolves once
per request. Routers depend on require_role(...); the routes only Dagster may call add system_only.
"""
import logging
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request

from app.helpers.exceptions import AuthenticationError, UnauthorizedError
from app.helpers.keycloak import KEYCLOAK_CLIENT, KEYCLOAK_URL, REALM
from app.models.user import User

logger = logging.getLogger('wrappers')
logger.setLevel(logging.INFO)

# Tokens are issued for the public address (KC_HOSTNAME), keys are fetched in-cluster
KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", f"{KEYCLOAK_URL}/realms/{REALM}")
KEYCLOAK_JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL", f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs")

# The five node roles (ADR 0037). A caller holds exactly one; other realm roles (default-roles-*,
# offline_access, ...) are ignored.
SUPERUSER = "SuperUser"
ADMINISTRATOR = "Administrator"
SERVICE = "Service"
USERS = "Users"
DAGSTER = "Dagster"
NODE_ROLES = frozenset({SUPERUSER, ADMINISTRATOR, SERVICE, USERS, DAGSTER})
# The roles that manage the node: they may set `revoked` and see every task
ADMIN_ROLES = frozenset({SUPERUSER, ADMINISTRATOR, SERVICE})

# Keys are cached and refetched only when a token names a key id not in the cache (a key rotation)
_jwks_client = jwt.PyJWKClient(KEYCLOAK_JWKS_URL, cache_keys=True, lifespan=3600)


@dataclass
class Caller:
    # Keycloak's user id (sub)
    user_id: str
    # One of NODE_ROLES
    role: str
    groups: list[str]
    # The caller's row in users, created or refreshed on this call (ADR 0036)
    user: User

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def decode_access_token(token: str) -> dict:
    """
    The claims of a Keycloak access token issued to our client, or AuthenticationError. RS256 only; the
    audience is not checked (Keycloak sets `account` there), azp and typ are.
    """
    try:
        key = _jwks_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], issuer=KEYCLOAK_ISSUER,
            options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.info("Token refused: %s", exc)
        raise AuthenticationError("Token is not valid") from exc
    if claims.get("typ") != "Bearer" or claims.get("azp") != KEYCLOAK_CLIENT:
        raise AuthenticationError("Token is not valid")
    return claims


def get_caller(request: Request) -> Caller:
    """The verified caller, cached per request by FastAPI's dependency cache."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise AuthenticationError("Token not provided")

    claims = decode_access_token(token)
    roles = set(claims.get("realm_access", {}).get("roles", [])) & NODE_ROLES
    if len(roles) != 1:
        raise AuthenticationError("The user must hold exactly one node role")

    return Caller(
        user_id=claims["sub"],
        role=roles.pop(),
        groups=claims.get("groups", []),
        user=User.seen(claims["sub"], claims.get("preferred_username", claims["sub"])),
    )


def require_role(*roles: str):
    def _require_role(caller: Caller = Depends(get_caller)) -> Caller:
        if caller.role not in roles:
            raise UnauthorizedError("The user has not enough permissions.")
        return caller
    return _require_role


def system_only(caller: Caller = Depends(get_caller)) -> Caller:
    """Only Dagster may call it, whatever else the router allows. Goes next to the router's require_role."""
    if caller.role != DAGSTER:
        raise UnauthorizedError("Only the system user can change this state.")
    return caller
