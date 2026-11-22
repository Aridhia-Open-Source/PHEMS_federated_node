"""
nexus-api verifies access tokens itself (ADR 0036), so the global client no longer needs Keycloak
Authorization Services, and access tokens are short-lived: clients refresh them.

1. The global client's Authorization Services are turned off, which deletes its resources, scopes,
   policies and permissions.
2. Access tokens live 5 minutes (accessTokenLifespan), as realms.json sets for a fresh realm.

Each step is a no-op when already done, so it also runs cleanly on a fresh realm.
"""
import logging

import requests

from common import get_client_uuid, is_response_good
from settings import settings

logger = logging.getLogger('realm_migrations')

VERSION = 4
DESCRIPTION = "global client without Authorization Services, 5 minute access tokens"

ACCESS_TOKEN_LIFESPAN = 300


def _realm_url(path: str = "") -> str:
    return f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}{path}"


def _disable_authorization(token: str):
    headers = {'Authorization': f'Bearer {token}'}
    url = _realm_url(f"/clients/{get_client_uuid('global', token)}")
    found = requests.get(url, headers=headers)
    is_response_good(found)
    client = found.json()
    if not client.get("authorizationServicesEnabled"):
        return
    client["authorizationServicesEnabled"] = False
    client.pop("authorizationSettings", None)
    is_response_good(requests.put(url, headers=headers, json=client))


def _short_access_tokens(token: str):
    response = requests.put(
        _realm_url(), headers={'Authorization': f'Bearer {token}'},
        json={"accessTokenLifespan": ACCESS_TOKEN_LIFESPAN},
    )
    is_response_good(response)


def migrate(admin_token: str):
    _disable_authorization(admin_token)
    _short_access_tokens(admin_token)
