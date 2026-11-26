"""Checks Keycloak access tokens locally, against the realm's published keys (ADR 0035)."""
import logging

import jwt
from fednode.clients.keycloak.keys import KeycloakKeys

from app.settings import settings
from app.helpers.exceptions import AuthenticationError

logger = logging.getLogger('access_token')
logger.setLevel(logging.INFO)


class AccessTokenVerifier:
    """
    Keys are cached and refetched only when a token names a key id not in the cache (a key rotation), so a normal
    request makes no Keycloak call.
    """

    def __init__(self, issuer: str, allowed_clients: str, jwks_uri: str):
        self.issuer = issuer
        self.clients = {client.strip() for client in allowed_clients.split(",")}
        self.jwks = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)

    def claims(self, token: str) -> dict:
        """
        The claims of a Keycloak access token issued to one of the allowed clients, or AuthenticationError. RS256 only; the
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
            raise AuthenticationError("Token is not valid") from exc
        if claims.get("typ") != "Bearer" or claims.get("azp") not in self.clients:
            raise AuthenticationError("Token is not valid")
        return claims


keycloak = settings.services.keycloak
# The keys are fetched in-cluster; the issuer is on the node's host
access_tokens = AccessTokenVerifier(
    keycloak.issuer, keycloak.allowed_clients, KeycloakKeys(keycloak.url, keycloak.realm).jwks_uri
)
