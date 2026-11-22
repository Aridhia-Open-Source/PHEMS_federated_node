"""Checks Keycloak access tokens locally, against the realm's published keys (ADR 0036)."""
import logging

import jwt

from app.config import AccessTokenConfig
from app.helpers.exceptions import AuthenticationError

logger = logging.getLogger('access_token')
logger.setLevel(logging.INFO)


class AccessTokenVerifier:
    """
    Keys are cached and refetched only when a token names a key id not in the cache (a key rotation), so a normal
    request makes no Keycloak call.
    """

    def __init__(self, config: AccessTokenConfig):
        self.config = config
        self.jwks = jwt.PyJWKClient(config.jwks_url, cache_keys=True, lifespan=3600)

    def claims(self, token: str) -> dict:
        """
        The claims of a Keycloak access token issued to our client, or AuthenticationError. RS256 only; the
        audience is not checked (Keycloak sets `account` there), azp and typ are.
        """
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.config.issuer,
                options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            logger.info("Token refused: %s", exc)
            raise AuthenticationError("Token is not valid") from exc
        if claims.get("typ") != "Bearer" or claims.get("azp") != self.config.client:
            raise AuthenticationError("Token is not valid")
        return claims


access_tokens = AccessTokenVerifier(AccessTokenConfig())
