"""
nexus-api verifies Keycloak access tokens itself (ADR 0035), end to end: tokens signed with a test RSA key, the JWKS
lookup stubbed. The verifier's own checks are in nexus/fednode/tests/test_access_token.py; the rest of the suite
stubs access_tokens.claims (tests/conftest.py token_claims).
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fednode.clients.keycloak.keys import AccessTokenVerifier

from app.helpers.wrappers import access_tokens
from app.settings import settings
from tests.conftest import claims_for

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PROV = "/global/providers"
# The real check: the suite's access_tokens.claims is stubbed (tests/conftest.py token_claims)
JWKS_URI = "http://keycloak/realms/FederatedNode/protocol/openid-connect/certs"
keycloak = settings.services.keycloak
verifier = AccessTokenVerifier(keycloak.issuer, keycloak.allowed_clients, JWKS_URI)


def access_token(key=KEY, algorithm="RS256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": verifier.issuer, "sub": "user-1", "exp": now + 300, "iat": now, "typ": "Bearer", "azp": "global",
        "aud": ["account"], "preferred_username": "someone",
        "realm_access": {"roles": ["Users", "default-roles-federatednode", "offline_access"]},
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


@pytest.fixture
def real_verification(mocker):
    """get_caller runs the real check, undoing the conftest stub."""
    mocker.patch.object(access_tokens, "claims", verifier.claims)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_a_signed_admin_token_passes_end_to_end(client, real_verification):
    token = access_token(realm_access={"roles": ["Administrator", "default-roles-federatednode"]})
    assert client.get(PROV, headers=bearer(token)).status_code == 200


def test_a_bad_token_is_a_401_end_to_end(client, real_verification):
    assert client.get(PROV, headers=bearer(access_token(key=OTHER_KEY))).status_code == 401


@pytest.mark.parametrize("roles, status", [
    pytest.param([], 401, id="no node role"),
    pytest.param(["Administrator", "SuperUser"], 401, id="two node roles"),
    pytest.param(["default-roles-federatednode", "offline_access"], 401, id="only Keycloak roles"),
    pytest.param(["Users"], 403, id="Users on an admin router"),
    pytest.param(["Administrator", "offline_access"], 200, id="Keycloak roles ignored"),
    pytest.param(["Dagster"], 200, id="Dagster passes the admin routers"),
])
def test_the_caller_holds_exactly_one_node_role(client, token_claims, roles, status):
    token_claims["t"] = {**claims_for("id-t", "t", "Users"), "realm_access": {"roles": roles}}
    assert client.get(PROV, headers=bearer("t")).status_code == status


@pytest.mark.parametrize("caller_role, new_role, status", [
    pytest.param("Administrator", None, 201, id="Users by default"),
    pytest.param("Administrator", "Administrator", 403, id="only the SuperUser makes an Administrator"),
    pytest.param("SuperUser", "Administrator", 201, id="SuperUser makes an Administrator"),
    pytest.param("SuperUser", "Dagster", 400, id="no other role"),
])
def test_new_users_get_users_or_administrator(client, token_claims, mock_kc_client, caller_role, new_role, status):
    mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = None
    token_claims["t"] = claims_for("id-t", "t", caller_role)
    body = {"email": "new@example.com"} | ({"role": new_role} if new_role else {})
    assert client.post("/global/users", json=body, headers=bearer("t")).status_code == status
