"""
The admin REST API of one Keycloak realm, with the bearer token of an admin account.

Every call returns the response whatever its status: which statuses are fine (a 409 on create is "exists already") and
what a refusal means are the caller's rules (ADR 0021). A timeout or a connection failure is a ClientTimeout or a
ClientError. A client is `client_uuid` (Keycloak's id), never its `clientId` name, except in `find_clients`.
"""

from requests import Response

from fednode.http import DEFAULT_TIMEOUT, HttpClient

RESOURCE_SERVER = "authz/resource-server"


class KeycloakAdmin(HttpClient):
    def __init__(
        self, base_uri: str, realm: str, token: str, session=None, timeout: tuple[float, float] = DEFAULT_TIMEOUT
    ):
        super().__init__(f"{base_uri.rstrip('/')}/admin/realms/{realm}", token, session=session, timeout=timeout)

    def request(self, method: str, path: str, raise_for_status: bool = False, **kwargs) -> Response:
        return super().request(method, path, raise_for_status, **kwargs)

    # Clients
    def find_clients(self, client_id: str) -> Response:
        return self.get("/clients", params={"clientId": client_id})

    def create_client(self, body: dict) -> Response:
        return self.post("/clients", json=body)

    def client_secret(self, client_uuid: str) -> Response:
        return self.get(f"/clients/{client_uuid}/client-secret")

    def set_client_permissions(self, client_uuid: str, body: dict) -> Response:
        """Turns the client's management permissions (token exchange) on or off."""
        return self.put(f"/clients/{client_uuid}/management/permissions", json=body)

    def update_resource_server(self, client_uuid: str, body: dict) -> Response:
        return self.put(f"/clients/{client_uuid}/{RESOURCE_SERVER}", json=body)

    # Realm roles
    def get_role(self, name: str) -> Response:
        return self.get(f"/roles/{name}")

    # Authorization services of a client. `policy_type` is a suffix, "/user" or "/time".
    def policies(self, client_uuid: str, policy_type: str = "", **params) -> Response:
        return self.get(f"/clients/{client_uuid}/{RESOURCE_SERVER}/policy{policy_type}", params=params)

    def create_policy(self, client_uuid: str, policy_type: str, body: dict) -> Response:
        return self.post(f"/clients/{client_uuid}/{RESOURCE_SERVER}/policy{policy_type}", json=body)

    def update_policy(self, client_uuid: str, policy_id: str, body: dict) -> Response:
        return self.put(f"/clients/{client_uuid}/{RESOURCE_SERVER}/policy/{policy_id}", json=body)

    def scopes(self, client_uuid: str, **params) -> Response:
        return self.get(f"/clients/{client_uuid}/{RESOURCE_SERVER}/scope", params=params)

    def create_scope(self, client_uuid: str, body: dict) -> Response:
        return self.post(f"/clients/{client_uuid}/{RESOURCE_SERVER}/scope", json=body)

    def resources(self, client_uuid: str, **params) -> Response:
        return self.get(f"/clients/{client_uuid}/{RESOURCE_SERVER}/resource", params=params)

    def create_resource(self, client_uuid: str, body: dict) -> Response:
        return self.post(f"/clients/{client_uuid}/{RESOURCE_SERVER}/resource", json=body)

    def update_resource(self, client_uuid: str, resource_id: str, body: dict) -> Response:
        return self.put(f"/clients/{client_uuid}/{RESOURCE_SERVER}/resource/{resource_id}", json=body)

    def permissions(self, client_uuid: str, **params) -> Response:
        return self.get(f"/clients/{client_uuid}/{RESOURCE_SERVER}/permission/scope", params=params)

    def create_permission(self, client_uuid: str, body: dict) -> Response:
        return self.post(f"/clients/{client_uuid}/{RESOURCE_SERVER}/permission/scope", json=body)

    def update_permission(self, client_uuid: str, permission_id: str, body: dict) -> Response:
        return self.put(f"/clients/{client_uuid}/{RESOURCE_SERVER}/permission/scope/{permission_id}", json=body)

    # Users
    def users(self, **params) -> Response:
        return self.get("/users", params=params)

    def create_user(self, body: dict) -> Response:
        return self.post("/users", json=body)

    def user_roles(self, user_id: str) -> Response:
        return self.get(f"/users/{user_id}/role-mappings/realm")

    def assign_roles(self, user_id: str, roles: list[dict]) -> Response:
        return self.post(f"/users/{user_id}/role-mappings/realm", json=roles)

    def reset_password(self, user_id: str, body: dict) -> Response:
        return self.put(f"/users/{user_id}/reset-password", json=body)
