import pytest
from pytest import fixture
import responses
from responses import matchers
from app.config import settings
from app.helpers.exceptions import KeycloakError
from app.clients.keycloak import (
    URLS,
    Keycloak,
    keycloak_service_password,
)


class TestKeycloakMixin:
    """
    Collection of tests that aims to prove the correct exceptions are raised
        in case of failed requests in the context of the Keycloak class.
    An exception raised in this class will be then handled by the app's
        exception handlers. In order to make these tests less crowded
        and verbose the direct class method behaviour will be considered.
    """
    common_error_response = {"error": "invalid_grant", "error_description": "Test - Invalid refresh token"}

    @fixture
    def keycloak_login_request_mock(self, admin_user, admin_user_uuid, new_user):
        rsps = responses.RequestsMock(assert_all_requests_are_fired=False)
        rsps.start()
        rsps.add(
            responses.POST,
            URLS["get_token"],
            json={"access_token": "token", "refresh_token": "ref_token"},
            # Driven off the module constants rather than hardcoded literals. urlencoded_params_matcher
            # is an exact match, so a hardcoded username silently stops matching the moment the
            # credential the backend uses changes -- and the symptom is a confusing ConnectionError
            # from `responses` rather than an obviously wrong assertion.
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'admin-cli',
                        'grant_type': 'password',
                        'username': settings.keycloak.service_user,
                        'password': keycloak_service_password()
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=200
        )
        rsps.add(
            responses.POST,
            URLS["get_token"],
            json={"access_token": "token", "refresh_token": "ref_token"},
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'global',
                        'client_secret': 'clientsecret',
                        'grant_type': 'password',
                        'username': settings.keycloak.service_user,
                        'password': keycloak_service_password()
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=200
        )
        rsps.add(
            responses.POST,
            URLS["get_token"],
            json={"access_token": "token", "refresh_token": "ref_token"},
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'global',
                        'client_secret': 'clientsecret',
                        'grant_type': 'refresh_token',
                        'refresh_token': 'admin_token'
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=200
        )
        rsps.add(
            responses.POST,
            URLS["get_token"],
            json={"access_token": "user_token", "refresh_token": "user_ref_token"},
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'global',
                        'client_secret': 'clientsecret',
                        'grant_type': 'refresh_token',
                        'refresh_token': 'user_refresh_token'
                    }
                ),
                matchers.header_matcher({
                    "Content-Type": "application/x-www-form-urlencoded"
                })
            ],
            status=200
        )
        rsps.add(
            responses.POST,
            URLS["get_token"],
            match=[matchers.urlencoded_params_matcher({
                    'grant_type': 'urn:ietf:params:oauth:grant-type:uma-ticket',
                    'audience': 'global',
                    'response_mode': 'decision',
                    'permission': 'resid#can_do_admin'
                }),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["client"],
            json=[{"id": "clientid"}],
            match=[matchers.query_string_matcher("clientId=global")],
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["client_secret"] % "clientid",
            json={"value": "clientsecret"},
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["user"] + f"/{admin_user_uuid}",
            json=admin_user,
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["user"] + f"/{new_user["id"]}",
            json=new_user,
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["user_role"] % admin_user_uuid,
            json=[{"name": "User"}],
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["user_role"] % new_user["id"],
            json=[{"name": "User"}],
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["roles"] + "/Users",
            json=[{"name": "User"}],
            status=200
        )
        yield rsps
        rsps.stop()
        rsps.reset()


class TestKeycloakResponseFailures(TestKeycloakMixin):
    def test_get_client_secret(self, keycloak_login_request_mock):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on fetching the client secret
        """
        kc_client = Keycloak()
        # Mocking self.get_admin_token_global() request to be successful
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["client_secret"] % kc_client.client_id,
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client._get_client_secret()
        assert exc.value.description == f'Failed to fetch {kc_client.client_id}\'s secret'

    def test_get_role(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific role
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["roles"] + "/some_role",
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.get_role('some_role')
        assert exc.value.description == 'Failed to fetch roles'
