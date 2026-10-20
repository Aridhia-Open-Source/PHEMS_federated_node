import pytest
import responses
from responses import matchers

from app.helpers.exceptions import UnauthorizedError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakTokens(TestKeycloakMixin):
    """
    """
    def test_check_permissions(self, keycloak_login_request_mock, mocker):
        mocker.patch.object(Keycloak, "get_resource", return_value={"_id": "resource"})
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
                        "audience": "global",
                        "response_mode": "decision",
                        'permission': 'resource#can_admin_dataset'
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ]
        )
        Keycloak().check_permissions("token", "can_admin_dataset", "resource", is_access_token=True)

    def test_check_permissions_fails(self, keycloak_login_request_mock, mocker):
        mocker.patch.object(Keycloak, "get_resource", return_value={"_id": "resource"})
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
                        "audience": "global",
                        "response_mode": "decision",
                        'permission': 'resource#can_admin_dataset'
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=401
        )
        with pytest.raises(UnauthorizedError) as exc:
            Keycloak().check_permissions("token", "can_admin_dataset", "resource", is_access_token=True)
        assert exc.value.description == 'User is not authorized'

    def test_is_token_valid(self, keycloak_login_request_mock, mocker):
        # is_token_valid asks Keycloak whether the caller is a system user, which
        # bypasses the permission check. These cover the non-system branch.
        mocker.patch.object(Keycloak, "is_system_user", return_value=False)
        mocker.patch.object(Keycloak, "check_permissions", return_value=True)
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "grant_type": "refresh_token",
                        "refresh_token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ]
        )
        assert Keycloak().is_token_valid("token", "can_admin_dataset", "resource")

    def test_is_token_valid_passes_a_system_user_on_an_admin_scope(self, keycloak_login_request_mock, mocker):
        # The System role (Dagster, fncli) skips the permission check, so it passes can_do_admin, which the
        # realm gives to administrators only; is_user_admin, which `revoked` is gated on, is still False for it.
        mocker.patch.object(Keycloak, "decode_token", return_value={"realm_access": {"roles": ["System"]}})
        check = mocker.patch.object(
            Keycloak, "check_permissions", side_effect=UnauthorizedError("User is not authorized")
        )
        keycloak_login_request_mock.add(responses.POST, URLS["get_token"])
        keycloak_login_request_mock.add(responses.POST, URLS["validate"], json={"realm_access": {"roles": ["System"]}})
        kc = Keycloak()
        assert kc.is_token_valid("token", "can_do_admin", "resource")
        check.assert_not_called()
        assert not kc.is_user_admin("token")

    def test_is_token_valid_refuses_a_user_without_the_permission(self, keycloak_login_request_mock, mocker):
        mocker.patch.object(Keycloak, "decode_token", return_value={"realm_access": {"roles": ["Users"]}})
        mocker.patch.object(Keycloak, "check_permissions", side_effect=UnauthorizedError("User is not authorized"))
        keycloak_login_request_mock.add(responses.POST, URLS["get_token"])
        with pytest.raises(UnauthorizedError):
            Keycloak().is_token_valid("token", "can_do_admin", "resource")

    def test_is_token_valid_without_permission_check(self, keycloak_login_request_mock, mocker):
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "grant_type": "refresh_token",
                        "refresh_token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ]
        )
        assert Keycloak().is_token_valid("token", "can_admin_dataset", "resource", with_permissions=False)

    def test_is_token_valid_without_permission_check_fails(self, keycloak_login_request_mock, mocker):
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "grant_type": "refresh_token",
                        "refresh_token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=401
        )
        assert not Keycloak().is_token_valid("token", "can_admin_dataset", "resource", with_permissions=False)

    def test_is_token_valid_fails(self, keycloak_login_request_mock, mocker):
        # is_token_valid asks Keycloak whether the caller is a system user, which
        # bypasses the permission check. These cover the non-system branch.
        mocker.patch.object(Keycloak, "is_system_user", return_value=False)
        mocker.patch.object(Keycloak, "check_permissions", return_value=True)
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "grant_type": "refresh_token",
                        "refresh_token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=401
        )
        assert not Keycloak().is_token_valid("token", "can_admin_dataset", "resource")

    def test_is_token_valid_with_access(self, keycloak_login_request_mock, mocker):
        # is_token_valid asks Keycloak whether the caller is a system user, which
        # bypasses the permission check. These cover the non-system branch.
        mocker.patch.object(Keycloak, "is_system_user", return_value=False)
        mocker.patch.object(Keycloak, "check_permissions", return_value=True)
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["validate"],
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=200
        )
        assert Keycloak().is_token_valid("token", "can_admin_dataset", "resource", "access_token")
