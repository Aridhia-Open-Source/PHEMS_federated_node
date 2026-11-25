from unittest.mock import MagicMock

import pytest
import requests

from fednode.clients.keycloak.admin import KeycloakAdmin
from fednode.clients.keycloak.keys import KeycloakKeys
from fednode.clients.keycloak.login import KeycloakLogin
from fednode.http import ClientError, ClientTimeout

KC = "http://keycloak:8080"
REALM_URL = f"{KC}/realms/FederatedNode/protocol/openid-connect"
ADMIN_URL = f"{KC}/admin/realms/FederatedNode"
RESOURCE_SERVER = f"{ADMIN_URL}/clients/c1/authz/resource-server"


def reply(status_code=200, body=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = body
    return resp


@pytest.fixture
def session():
    mock = MagicMock()
    mock.request.return_value = reply()
    return mock


@pytest.fixture
def login(session):
    return KeycloakLogin(KC + "/", "FederatedNode", session=session)


@pytest.fixture
def admin(session):
    return KeycloakAdmin(KC + "/", "FederatedNode", "admin-token", session=session)


def sent(session):
    """The method, url and keyword arguments of the one request made."""
    (method, url), kwargs = session.request.call_args.args, session.request.call_args.kwargs
    return method, url, kwargs


# KeycloakLogin


def test_the_login_session_carries_no_authorization():
    client = KeycloakLogin(KC, "FederatedNode")

    assert "Authorization" not in client._session.headers


def test_a_password_grant_is_a_form_posted_to_the_realm_token_endpoint(login, session):
    login.password_grant("global", "fn-service", "pw", "secret")

    method, url, kwargs = sent(session)
    assert (method, url) == ("POST", f"{REALM_URL}/token")
    assert kwargs["data"] == {
        "client_id": "global", "client_secret": "secret", "grant_type": "password",
        "username": "fn-service", "password": "pw",
    }
    assert kwargs["timeout"] == (3, 10)


def test_a_public_client_sends_no_secret(login, session):
    login.password_grant("admin-cli", "fn-service", "pw")

    assert "client_secret" not in sent(session)[2]["data"]


def test_a_refresh_grant(login, session):
    login.refresh_grant("global", "secret", "refresh")

    assert sent(session)[2]["data"] == {
        "client_id": "global", "client_secret": "secret", "grant_type": "refresh_token", "refresh_token": "refresh",
    }


def test_a_token_exchange_for_the_audience_client(login, session):
    login.exchange_grant("global", "secret", "access", "project-1", "access_token")

    assert sent(session)[2]["data"] == {
        "client_id": "global",
        "client_secret": "secret",
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "subject_token": "access",
        "audience": "project-1",
    }


def test_an_impersonation_names_the_user(login, session):
    login.exchange_grant("global", "secret", "access", "global", "refresh_token", requested_subject="user-1")

    data = sent(session)[2]["data"]
    assert data["requested_subject"] == "user-1"
    assert data["requested_token_type"] == "urn:ietf:params:oauth:token-type:refresh_token"


def test_a_permission_decision_is_asked_with_the_users_own_token(login, session):
    login.permission_decision("access", "global", "res-1#can_read")

    method, url, kwargs = sent(session)
    assert (method, url) == ("POST", f"{REALM_URL}/token")
    assert kwargs["headers"] == {"Authorization": "Bearer access"}
    assert kwargs["data"] == {
        "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
        "audience": "global",
        "response_mode": "decision",
        "permission": "res-1#can_read",
    }


def test_introspection_posts_the_token_with_the_client_credentials(login, session):
    login.introspect("global", "secret", "access")

    method, url, kwargs = sent(session)
    assert (method, url) == ("POST", f"{REALM_URL}/token/introspect")
    assert kwargs["data"] == {"client_id": "global", "client_secret": "secret", "token": "access"}


def test_the_realm_page_is_a_get_of_that_realm(session):
    KeycloakLogin(KC, "master", session=session).realm_info()

    assert sent(session)[:2] == ("GET", f"{KC}/realms/master")


def test_a_refused_login_is_returned_not_raised(login, session):
    session.request.return_value = reply(401, {"error": "invalid_grant"})

    response = login.password_grant("global", "fn-service", "wrong", "secret")

    assert response.status_code == 401
    response.raise_for_status.assert_not_called()


def test_the_timeout_can_be_overridden(session):
    KeycloakLogin(KC, "FederatedNode", session=session, timeout=(3, 30)).realm_info()

    assert sent(session)[2]["timeout"] == (3, 30)


def test_a_timeout_is_a_client_timeout(login, session):
    session.request.side_effect = requests.ReadTimeout("slow")

    with pytest.raises(ClientTimeout):
        login.password_grant("global", "fn-service", "pw", "secret")


def test_an_unreachable_keycloak_is_a_client_error(login, session):
    session.request.side_effect = requests.ConnectionError("refused")

    with pytest.raises(ClientError) as raised:
        login.realm_info()

    assert not isinstance(raised.value, ClientTimeout)


# KeycloakAdmin


def test_the_admin_session_carries_the_bearer_token():
    client = KeycloakAdmin(KC, "FederatedNode", "admin-token")

    assert client._session.headers["Authorization"] == "Bearer admin-token"


# method, arguments, verb, path under the realm, request keyword arguments
ADMIN_CALLS = [
    ("find_clients", ("global",), "GET", "/clients", {"params": {"clientId": "global"}}),
    ("create_client", ({"clientId": "p"},), "POST", "/clients", {"json": {"clientId": "p"}}),
    ("client_secret", ("c1",), "GET", "/clients/c1/client-secret", {}),
    ("set_client_permissions", ("c1", {"enabled": True}), "PUT", "/clients/c1/management/permissions",
     {"json": {"enabled": True}}),
    ("update_resource_server", ("c1", {"a": 1}), "PUT", "/clients/c1/authz/resource-server", {"json": {"a": 1}}),
    ("get_role", ("Users",), "GET", "/roles/Users", {}),
    ("policies", ("c1",), "GET", "/clients/c1/authz/resource-server/policy", {"params": {}}),
    ("create_policy", ("c1", "/user", {"a": 1}), "POST", "/clients/c1/authz/resource-server/policy/user",
     {"json": {"a": 1}}),
    ("update_policy", ("c1", "p1", {"a": 1}), "PUT", "/clients/c1/authz/resource-server/policy/p1", {"json": {"a": 1}}),
    ("scopes", ("c1",), "GET", "/clients/c1/authz/resource-server/scope", {"params": {}}),
    ("create_scope", ("c1", {"a": 1}), "POST", "/clients/c1/authz/resource-server/scope", {"json": {"a": 1}}),
    ("resources", ("c1",), "GET", "/clients/c1/authz/resource-server/resource", {"params": {}}),
    ("create_resource", ("c1", {"a": 1}), "POST", "/clients/c1/authz/resource-server/resource", {"json": {"a": 1}}),
    ("update_resource", ("c1", "r1", {"a": 1}), "PUT", "/clients/c1/authz/resource-server/resource/r1",
     {"json": {"a": 1}}),
    ("permissions", ("c1",), "GET", "/clients/c1/authz/resource-server/permission/scope", {"params": {}}),
    ("create_permission", ("c1", {"a": 1}), "POST", "/clients/c1/authz/resource-server/permission/scope",
     {"json": {"a": 1}}),
    ("update_permission", ("c1", "m1", {"a": 1}), "PUT", "/clients/c1/authz/resource-server/permission/scope/m1",
     {"json": {"a": 1}}),
    ("users", (), "GET", "/users", {"params": {}}),
    ("create_user", ({"username": "u"},), "POST", "/users", {"json": {"username": "u"}}),
    ("user_roles", ("u1",), "GET", "/users/u1/role-mappings/realm", {}),
    ("assign_roles", ("u1", [{"name": "Users"}]), "POST", "/users/u1/role-mappings/realm",
     {"json": [{"name": "Users"}]}),
    ("reset_password", ("u1", {"value": "pw"}), "PUT", "/users/u1/reset-password", {"json": {"value": "pw"}}),
]


@pytest.mark.parametrize(("name", "args", "verb", "path", "extra"), ADMIN_CALLS, ids=[c[0] for c in ADMIN_CALLS])
def test_each_admin_call_goes_to_its_realm_path(admin, session, name, args, verb, path, extra):
    getattr(admin, name)(*args)

    method, url, kwargs = sent(session)
    assert (method, url) == (verb, f"{ADMIN_URL}{path}")
    assert {key: value for key, value in kwargs.items() if key != "timeout"} == extra
    assert kwargs["timeout"] == (3, 10)


def test_query_parameters_keep_their_order_and_their_values(admin, session):
    admin.scopes("c1", permission=False, name="token-exchange")
    assert sent(session)[2]["params"] == {"permission": False, "name": "token-exchange"}

    admin.users(username="a@b.c", exact=True)
    assert sent(session)[2]["params"] == {"username": "a@b.c", "exact": True}


def test_a_policy_type_is_a_suffix_of_the_policy_path(admin, session):
    admin.policies("c1", "/client", name="token-exchange-global")

    assert sent(session)[:2] == ("GET", f"{RESOURCE_SERVER}/policy/client")
    assert sent(session)[2]["params"] == {"name": "token-exchange-global"}


@pytest.mark.parametrize("status", [404, 409, 500])
def test_an_admin_error_status_is_returned_not_raised(admin, session, status):
    session.request.return_value = reply(status)

    response = admin.create_user({"username": "u"})

    assert response.status_code == status
    response.raise_for_status.assert_not_called()


def test_an_admin_timeout_is_a_client_timeout(admin, session):
    session.request.side_effect = requests.ConnectTimeout("slow")

    with pytest.raises(ClientTimeout):
        admin.users()


# KeycloakKeys


def test_the_signing_keys_are_read_from_the_realm_certs_endpoint(session):
    keys = KeycloakKeys(KC + "/", "FederatedNode", session=session)
    session.request.return_value = reply(200, {"keys": [{"kid": "k1"}]})

    assert keys.jwks() == {"keys": [{"kid": "k1"}]}
    assert sent(session)[:2] == ("GET", f"{REALM_URL}/certs")
    assert keys.jwks_uri == f"{REALM_URL}/certs"


def test_an_error_status_for_the_keys_is_a_client_error(session):
    session.request.return_value = reply(503)

    with pytest.raises(ClientError, match="503"):
        KeycloakKeys(KC, "FederatedNode", session=session).jwks()


def test_a_timeout_reading_the_keys_is_a_client_timeout(session):
    session.request.side_effect = requests.ReadTimeout("slow")

    with pytest.raises(ClientTimeout):
        KeycloakKeys(KC, "FederatedNode", session=session).jwks()
