import pytest
from pytest import fixture
import responses
from responses import matchers
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak


class TestKeycloakMixin:
    """
    Collection of tests that aims to prove the correct exceptions are raised
        in case of failed requests in the context of the Keycloak class.
    An exception raised in this class will be then handled by the Flask's
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
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'admin-cli',
                        'grant_type': 'password',
                        'username': 'admin',
                        'password': 'password1'
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
                        'username': 'admin',
                        'password': 'password1'
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
            URLS["resource"] % "clientid",
            json=[{"_id": "resid"}],
            match=[matchers.query_string_matcher("name=endpoints")],
            status=200
        )
        rsps.add(
            responses.GET,
            URLS["resource"] % "clientid",
            json=[{"_id": "resid"}],
            match=[matchers.query_string_matcher("name=1-testds")],
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
    def test_exchange_global_token_access_token(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on access_token fetching
        """
        kc_client = Keycloak()
        # Mocking the requests for the specific token
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json={"error": "Invalid credentials"},
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.exchange_global_token('not a token')
        assert exc.value.description == 'Cannot get an access token'

    def test_exchange_global_token(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on token exchange
        """
        kc_client = Keycloak()
        # Mock the request in the order they are submitted.
        # Unfortunately the match param doesn't detect form data
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json={"access_token": "random token"},
            content_type='application/x-www-form-urlencoded',
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json=self.common_error_response,
            content_type='application/x-www-form-urlencoded',
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.exchange_global_token('not a token')
        assert exc.value.description == 'Cannot exchange token'

    def test_impersonation_token(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on impersonation token
        """
        kc_client = Keycloak()
        # Mocking self.get_admin_token_global() request to be successful
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json={"access_token": "random token"},
            content_type='application/x-www-form-urlencoded',
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json=self.common_error_response,
            content_type='application/x-www-form-urlencoded',
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.get_impersonation_token('some user id')
        assert exc.value.description == 'Cannot exchange impersonation token'

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

    def test_get_resource(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific permission
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["resource"] % kc_client.client_id) + "?name=some_resource",
            json=[{"_id": "resource_id"}]
        )
        kc_client.get_resource('some_resource')

    def test_get_resource_empty_list_fails(
            self, keycloak_login_request_mock
    ):
        """
        Test that no exception is raised when the
        keycloak API is successful but no match is returned in the results list
        on getting a specific permission
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["resource"] % kc_client.client_id) + "?name=some_resource",
            json=[]
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.get_resource('some_resource')
        assert exc.value.description == 'Failed to fetch the resource'

    def test_get_resource_fails(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific permission
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["resource"] % kc_client.client_id) + "?name=some_resource",
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.get_resource('some_resource')
        assert exc.value.description == 'Failed to fetch the resource'

    def test_create_resource(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new resource
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["resource"] % kc_client.client_id,
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.create_resource({'name': 'some_resource'})
        assert exc.value.description == 'Failed to create a project\'s resource'

    def test_patch_resource(self, keycloak_login_request_mock):
        """
        patch_resource does not return an object, only ensures
        the keycloak API call is successful.
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["resource"] % kc_client.client_id) + "?name=some_resource",
            json=[{"_id": "resource_id"}]
        )
        keycloak_login_request_mock.add(
            responses.PUT,
            (URLS["resource"] % kc_client.client_id) + "/resource_id",
            json=[{"id": "resource_id"}]
        )
        kc_client.patch_resource("some_resource", **{"name": "new_name"})

    def test_patch_resource_fails(self, keycloak_login_request_mock):
        """
        patch_resource does not return an object, only ensures
        a custom exception is raised if the keycloak API call fails
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["resource"] % kc_client.client_id) + "?name=some_resource",
            json=[{"_id": "resource_id"}]
        )
        keycloak_login_request_mock.add(
            responses.PUT,
            (URLS["resource"] % kc_client.client_id) + "/resource_id",
            status=400
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.patch_resource("some_resource", **{"name": "new_name"})
        assert exc.value.description == 'Failed to patch the resource'
