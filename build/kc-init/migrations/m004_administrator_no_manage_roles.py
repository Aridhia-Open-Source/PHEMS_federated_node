"""
Take the realm-management manage-* roles away from Administrator in an existing realm (ADR 0036).

An Administrator holding manage-users or manage-clients can add itself to /roles/superuser and read
the global client's secret through the Keycloak admin API, so only SuperUser and the service account
administer the realm. realms.json no longer gives them to Administrator, but it is only imported into
a new realm; this removes them from a realm that exists. A no-op when they are already gone.
"""
import requests

from common import get_client_uuid, is_response_good
from settings import settings

VERSION = 4
DESCRIPTION = "Administrator loses realm-management manage-users, manage-clients and manage-authorization"

DROPPED = ("manage-users", "manage-clients", "manage-authorization")


def migrate(admin_token: str):
    headers = {'Authorization': f'Bearer {admin_token}'}
    realm_url = f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}"
    client_uuid = get_client_uuid("realm-management", admin_token)
    held = requests.get(f"{realm_url}/roles/Administrator/composites/clients/{client_uuid}", headers=headers)
    is_response_good(held)
    drop = [role for role in held.json() if role["name"] in DROPPED]
    if drop:
        is_response_good(requests.delete(f"{realm_url}/roles/Administrator/composites", headers=headers, json=drop))
