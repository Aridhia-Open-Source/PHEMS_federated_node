"""
Give the global client Keycloak's `basic` client scope, which puts `sub` (and `auth_time`) in its tokens.

nexus-api requires `sub` in every access token (ADR 0036: it is the caller's user id). Since Keycloak 25
`sub` comes from the `basic` scope, and realms.json listed the global client's default scopes without it,
so every token was refused as "missing the sub claim". realms.json now lists it for a fresh realm; this
adds it to an existing one. Adding a default scope the client already has is a no-op.
"""
import requests

from common import get_client_uuid, is_response_good
from settings import settings

VERSION = 4
DESCRIPTION = "basic client scope (the sub claim) on the global client"


def migrate(admin_token: str):
    headers = {'Authorization': f'Bearer {admin_token}'}
    realm_url = f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}"
    response = requests.get(f"{realm_url}/client-scopes", headers=headers)
    is_response_good(response)
    scope_id = next(scope["id"] for scope in response.json() if scope["name"] == "basic")
    client_id = get_client_uuid("global", admin_token)
    response = requests.put(f"{realm_url}/clients/{client_id}/default-client-scopes/{scope_id}", headers=headers)
    is_response_good(response)
