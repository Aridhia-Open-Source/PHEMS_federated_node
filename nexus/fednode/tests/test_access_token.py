"""
AccessTokenVerifier checks Keycloak access tokens locally (ADR 0035): tokens signed with a test RSA key, the JWKS
lookup stubbed.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fednode.clients.keycloak.keys import AccessTokenVerifier, InvalidToken

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISSUER = "https://node.example/realms/FederatedNode"
JWKS_URI = "http://keycloak/realms/FederatedNode/protocol/openid-connect/certs"
verifier = AccessTokenVerifier(ISSUER, "global", JWKS_URI)


def access_token(key=KEY, algorithm="RS256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER, "sub": "user-1", "exp": now + 300, "iat": now, "typ": "Bearer", "azp": "global",
        "aud": ["account"], "preferred_username": "someone",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "test"})


@pytest.fixture(autouse=True)
def jwks(mocker):
    """Keycloak's published key is KEY's public half."""
    return mocker.patch.object(
        jwt.PyJWKClient, "get_signing_key_from_jwt", return_value=SimpleNamespace(key=KEY.public_key())
    )


def test_a_valid_token_gives_its_claims():
    claims = verifier.claims(access_token())
    assert (claims["sub"], claims["preferred_username"]) == ("user-1", "someone")


def test_a_token_of_any_allowed_client_is_accepted():
    several = AccessTokenVerifier(ISSUER, "global, dagster", JWKS_URI)
    assert several.claims(access_token(azp="dagster"))["azp"] == "dagster"
    assert several.claims(access_token(azp="global"))["azp"] == "global"
    with pytest.raises(InvalidToken):
        several.claims(access_token(azp="another-client"))


@pytest.mark.parametrize("token", [
    pytest.param(access_token(exp=int(time.time()) - 10), id="expired"),
    pytest.param(access_token(iss="https://elsewhere/realms/FederatedNode"), id="wrong issuer"),
    pytest.param(access_token(key=OTHER_KEY), id="wrong key"),
    pytest.param(access_token(key="a-shared-secret-of-thirty-two-bytes", algorithm="HS256"), id="HS256"),
    pytest.param(access_token(typ="Refresh"), id="refresh token"),
    pytest.param(access_token(typ="ID"), id="ID token"),
    pytest.param(access_token(azp="another-client"), id="another client"),
    pytest.param(access_token(sub=None), id="no sub"),
    pytest.param("not-a-jwt", id="garbage"),
])
def test_a_bad_token_is_refused(token):
    with pytest.raises(InvalidToken):
        verifier.claims(token)
