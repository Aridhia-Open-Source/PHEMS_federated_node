"""Keycloak: login, the admin REST API and the realm signing keys."""
from fednode.http import ClientError


class KeycloakError(ClientError):
    """Keycloak failed a request, or answered something this node cannot use. `code` is the status the node answers with."""
    code = 500

    def __init__(self, message: str, code: int | None = None) -> None:
        self.description = message
        if code:
            self.code = code
        super().__init__(message)
