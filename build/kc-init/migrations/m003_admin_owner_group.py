"""
Make every Administrator hold the `admin` owner-group role (ADR 0036).

realms.json lists `admin` as a composite of Administrator, but on an existing realm partial_import
skips Administrator because it already exists, so the composite has to be added here. partial_import
runs first, so the `admin` role exists by now. Adding a composite that is already there is a no-op.
"""
from urllib.parse import quote

import requests

from common import get_role, is_response_good
from settings import settings

VERSION = 3
DESCRIPTION = "Administrator includes the admin owner-group role"


def migrate(admin_token: str):
    role_id = get_role("admin", admin_token)
    response = requests.post(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/roles/"
        f"{quote('Administrator', safe='')}/composites",
        json=[{"id": role_id, "name": "admin"}],
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(response)
