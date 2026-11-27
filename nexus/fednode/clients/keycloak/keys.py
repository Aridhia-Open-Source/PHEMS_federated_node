"""
The signing keys of one Keycloak realm: the public JWKS a service verifies access tokens against, and the local
check of an access token against them (ADR 0035).
"""
import logging

import jwt

from fednode.http import DEFAULT_TIMEOUT, ClientError, HttpClient

logger = logging.getLogger(__name__)


class InvalidToken(Exception):
    """An access token that is not a valid Keycloak access token of an allowed client."""


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


class AccessTokenVerifier:
    """
    Checks Keycloak access tokens locally, against the realm's published keys. Keys are cached and refetched only
    when a token names a key id not in the cache (a key rotation), so a normal request makes no Keycloak call.
    """

    def __init__(self, issuer: str, allowed_clients: str, jwks_uri: str):
        self.issuer = issuer
        self.clients = {client.strip() for client in allowed_clients.split(",")}
        self.jwks = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)

    def claims(self, token: str) -> dict:
        """
        The claims of a Keycloak access token issued to one of the allowed clients, or InvalidToken. RS256 only; the
        audience is not checked (Keycloak sets `account` there), azp and typ are.
        """
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            logger.info("Token refused: %s", exc)
            raise InvalidToken("Token is not valid") from exc
        if claims.get("typ") != "Bearer" or claims.get("azp") not in self.clients:
            raise InvalidToken("Token is not valid")
        return claims
