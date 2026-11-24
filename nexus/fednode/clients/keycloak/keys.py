"""
The signing keys of one Keycloak realm: the public JWKS a service verifies access tokens against.
"""

from fednode.http import DEFAULT_TIMEOUT, ClientError, HttpClient


class KeycloakKeys(HttpClient):
    def __init__(self, base_uri: str, realm: str, session=None, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        super().__init__(base_uri, session=session, timeout=timeout)
        self._path = f"/realms/{realm}/protocol/openid-connect/certs"

    @property
    def jwks_uri(self) -> str:
        """For a verifier that fetches the keys itself."""
        return f"{self._base_uri}{self._path}"

    def jwks(self) -> dict:
        """The key set. Anything but the keys is a ClientError."""
        response = self.get(self._path, raise_for_status=False)
        if not response.ok:
            raise ClientError(f"Keycloak answered {response.status_code} for the realm's signing keys")
        return response.json()
