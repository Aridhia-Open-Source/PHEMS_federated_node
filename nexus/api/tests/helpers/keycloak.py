## This file should just include a keycloak method that cleans up
# users, clients and other permissions. We could simply mock all calls
# but this way we can also test keycloak's configuration
import requests

from app.clients.keycloak import KEYCLOAK_SERVICE_USER, KEYCLOAK_URL, REALM, Keycloak

# The Keycloak URLs the tests mock, written out so they check the paths the shared client builds (fednode)
ADMIN = f"{KEYCLOAK_URL}/admin/realms/{REALM}"
URLS = {
    "get_token": f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
    "validate": f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token/introspect",
    "client": f"{ADMIN}/clients",
    "client_secret": f"{ADMIN}/clients/%s/client-secret",
    "client_exchange": f"{ADMIN}/clients/%s/management/permissions",
    "client_auth": f"{ADMIN}/clients/%s/authz/resource-server",
    "roles": f"{ADMIN}/roles",
    "policies": f"{ADMIN}/clients/%s/authz/resource-server/policy",
    "scopes": f"{ADMIN}/clients/%s/authz/resource-server/scope",
    "resource": f"{ADMIN}/clients/%s/authz/resource-server/resource",
    "permission": f"{ADMIN}/clients/%s/authz/resource-server/permission/scope",
    "user": f"{ADMIN}/users",
    "user_role": f"{ADMIN}/users/%s/role-mappings/realm",
    "user_reset": f"{ADMIN}/users/%s/reset-password",
}

PROTECTED_USERNAMES = {"admin", KEYCLOAK_SERVICE_USER}

def clean_kc():
    """
    Removes all users except the platform's own accounts
    """
    token = Keycloak().get_admin_token_global()
    response = requests.get(
        URLS["user"],
        headers={"Authorization": f"Bearer {token}"}
    )
    for user in response.json():
        if user["username"] not in PROTECTED_USERNAMES:
            requests.delete(
                URLS["user"] + f"/{user["id"]}",
                headers={"Authorization": f"Bearer {token}"}
            )
