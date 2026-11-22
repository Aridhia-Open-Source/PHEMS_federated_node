"""
Move an existing realm to the five node roles held through /roles groups (ADR 0037).

partial_import has already added the new roles (SuperUser, Service, Dagster) and the /roles groups,
but it skips everything that exists: the Administrator composite, the global client's role
policies and its mappers, and the people holding the old roles. This does the rest, in an order
that never leaves anyone without a role:

1. fn-service gets realm-admin directly, before Super Administrator (which gave it) goes.
2. Administrator stops including Users; the global client gets the groups mapper.
3. Each /roles group carries its role. (The global client's role policies are not repointed: nexus-api
   no longer uses Authorization Services (ADR 0036), and a fresh realm has none.)
4. Everyone holding an old role, directly or through an old group, joins the one /roles group for
   their highest role, and loses the direct Administrator or Users mapping.
5. The old roles and groups are deleted.

Each step is a no-op when already done, so it also runs cleanly on a fresh realm.
"""
import logging
from urllib.parse import quote

import requests

from common import assign_client_roles, get_client_uuid, get_role, is_response_good, join_group
from settings import settings

logger = logging.getLogger('realm_migrations')

VERSION = 3
DESCRIPTION = "five node roles held through /roles groups, old roles and groups removed"

# Old role or group name -> the /roles group that replaces it, highest first: someone holding
# several joins only the first, so their token carries one node role.
OLD_TO_GROUP = {
    "Super Administrator": "/roles/superuser",
    "Administrator": "/roles/admins",
    "System": "/roles/dagster",
    "Users": "/roles/users",
}
OLD_ROLES = ("Super Administrator", "System")
ROLE_GROUPS = {
    "/roles/superuser": "SuperUser", "/roles/admins": "Administrator", "/roles/service": "Service",
    "/roles/users": "Users", "/roles/dagster": "Dagster",
}
GROUPS_MAPPER = {
    "name": "groups", "protocol": "openid-connect", "protocolMapper": "oidc-group-membership-mapper",
    "config": {
        "claim.name": "groups", "full.path": "true", "access.token.claim": "true", "id.token.claim": "true",
        "userinfo.token.claim": "true", "introspection.token.claim": "true",
    },
}


def _url(path: str) -> str:
    return f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}{path}"


def _get(path: str, token: str, **params):
    return requests.get(_url(path), params=params, headers={'Authorization': f'Bearer {token}'})


def _paged(path: str, token: str) -> list:
    found, first = [], 0
    while True:
        response = _get(path, token, first=first, max=100)
        is_response_good(response)
        page = response.json()
        found += page
        if len(page) < 100:
            return found
        first += 100


def _role(name: str, token: str):
    """The role's representation, or None when the realm has no such role."""
    response = _get(f"/roles/{quote(name, safe='')}", token)
    return response.json() if response.ok else None


def _group_id(name: str, token: str):
    """A top-level group's id, or None when there is none."""
    response = _get(f"/group-by-path/{quote(name)}", token)
    return response.json()["id"] if response.ok else None


def _service_account(token: str):
    users = _get("/users", token, username=settings.keycloak_service_user, exact="true").json()
    if users:
        assign_client_roles(users[0]["id"], "realm-management", ["realm-admin"], token)
        return users[0]["id"]
    return None


def _drop_users_from_administrator(token: str):
    users_role = _role("Users", token)
    response = requests.delete(
        _url(f"/roles/{quote('Administrator', safe='')}/composites"),
        headers={'Authorization': f'Bearer {token}'}, json=[users_role]
    )
    is_response_good(response)


def _add_groups_mapper(client_uuid: str, token: str):
    response = requests.post(
        _url(f"/clients/{client_uuid}/protocol-mappers/models"),
        headers={'Authorization': f'Bearer {token}'}, json=GROUPS_MAPPER
    )
    is_response_good(response)


def _map_group_roles(token: str):
    """Each /roles group carries its role, whatever partial_import did with the subgroups' mappings."""
    for path, role in ROLE_GROUPS.items():
        found = _get(f"/group-by-path/{quote(path.lstrip('/'))}", token)
        is_response_good(found)
        response = requests.post(
            _url(f"/groups/{found.json()['id']}/role-mappings/realm"),
            headers={'Authorization': f'Bearer {token}'}, json=[_role(role, token)]
        )
        is_response_good(response)


def _move_people(service_id, token: str):
    """Each holder of an old role or group joins the /roles group of their highest one."""
    target = {}
    for old, group in reversed(OLD_TO_GROUP.items()):
        holders = []
        if _role(old, token):
            holders += _paged(f"/roles/{quote(old, safe='')}/users", token)
        group_id = _group_id(old, token)
        if group_id:
            holders += _paged(f"/groups/{group_id}/members", token)
        for user in holders:
            # Later (higher) roles overwrite earlier ones
            target[user["id"]] = group
    target.pop(service_id, None)

    direct = {name: _role(name, token) for name in ("Administrator", "Users")}
    for user_id, group in target.items():
        logger.info(f"Moving user {user_id} to {group}")
        join_group(user_id, group, token)
        response = requests.delete(
            _url(f"/users/{user_id}/role-mappings/realm"),
            headers={'Authorization': f'Bearer {token}'}, json=[r for r in direct.values() if r]
        )
        is_response_good(response)


def _delete_old(token: str):
    for name in OLD_TO_GROUP:
        group_id = _group_id(name, token)
        if group_id:
            is_response_good(requests.delete(_url(f"/groups/{group_id}"), headers={'Authorization': f'Bearer {token}'}))
    for name in OLD_ROLES:
        if _role(name, token):
            is_response_good(requests.delete(
                _url(f"/roles/{quote(name, safe='')}"), headers={'Authorization': f'Bearer {token}'}
            ))


def migrate(admin_token: str):
    service_id = _service_account(admin_token)
    _drop_users_from_administrator(admin_token)
    client_uuid = get_client_uuid("global", admin_token)
    _add_groups_mapper(client_uuid, admin_token)
    _map_group_roles(admin_token)
    _move_people(service_id, admin_token)
    _delete_old(admin_token)
