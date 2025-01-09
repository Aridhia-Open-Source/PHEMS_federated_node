import pytest
import responses
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak

class TestKeycloakResponseFailures:
    """
    Collection of tests that aims to prove the correct exceptions are raised
        in case of failed requests in the context of the Keycloak class.
    An exception raised in this class will be then handled by the Flask's
        exception handlers. In order to make these tests less crowded
        and verbose the direct class method behaviour will be considered.
    """
    common_error_response = {"error": "invalid_grant", "error_description": "Test - Invalid refresh token"}

    def test_exchange_global_token_access_token(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on access_token fetching
        """
        kc_client = Keycloak()
        # Mocking the requests for the specific token
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"error": "Invalid credentials"},
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.exchange_global_token('not a token')
            assert exc.value.details == 'Cannot get an access token'

    def test_exchange_global_token(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on token exchange
        """
        kc_client = Keycloak()
        # Mocking the requests for the specific token
        with responses.RequestsMock() as rsps:
            # Mock the request in the order they are submitted.
            # Unfortunately the match param doesn't detect form data
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"access_token": "random token"},
                content_type='application/x-www-form-urlencoded',
                status=200
            )
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json=self.common_error_response,
                content_type='application/x-www-form-urlencoded',
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.exchange_global_token('not a token')
            assert exc.value.details == 'Cannot exchange token'

    def test_impersonation_token(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on impersonation token
        """
        kc_client = Keycloak()
        # Mocking the requests for the specific token
        with responses.RequestsMock() as rsps:
            # Mocking self.get_admin_token_global() request to be successful
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"access_token": "random token"},
                content_type='application/x-www-form-urlencoded',
                status=200
            )
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json=self.common_error_response,
                content_type='application/x-www-form-urlencoded',
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.get_impersonation_token('some user id')
            assert exc.value.details == 'Cannot exchange impersonation token'

    def test_get_client_secret(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on fetching the client secret
        """
        kc_client = Keycloak()
        # Mocking the requests for the specific token
        with responses.RequestsMock() as rsps:
            # Mocking self.get_admin_token_global() request to be successful
            rsps.add(
                responses.GET,
                URLS["client_secret"] % kc_client.client_id,
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client._get_client_secret()
            assert exc.value.details == 'Failed to fetch client\'s secret'

    def test_get_client_id(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on fetching a client id.
        Usually invoked during the class init
        """
        # Mocking the requests for the specific token
        with responses.RequestsMock() as rsps:
            # Mocking self.get_admin_token() request to be successful
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"access_token": "random token"},
                content_type='application/x-www-form-urlencoded',
                status=200
            )
            rsps.add(
                responses.GET,
                URLS["client_id"] + 'global',
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                Keycloak()
            assert exc.value.details == 'Could not find client'

    def test_get_role(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific role
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                URLS["roles"] + "/some_role",
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.get_role('some_role')
            assert exc.value.details == 'Failed to fetch roles'

    def test_get_resource(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific permission
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                (URLS["resource"] % kc_client.client_id) + "?name=some_resource",
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.get_resource('some_resource')
            assert exc.value.details == 'Failed to fetch the resource'

    def test_get_policy(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific policy
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                (URLS["get_policies"] % kc_client.client_id) + "&name=some_policy",
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.get_policy('some_policy')
            assert exc.value.details == 'Error when fetching the policies from Keycloak'

    def test_get_scope(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific policy
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                (URLS["scopes"] % kc_client.client_id) + "?permission=false&name=some_scope",
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.get_scope('some_scope')
            assert exc.value.details == 'Error when fetching the scopes from Keycloak'

    def test_get_user(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a user by its username
        """
        kc_client = Keycloak()
        username = 'some@email.com'
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f'{URLS["user"]}?username={username}&exact=true',
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.get_user(username)
            assert exc.value.details == 'Failed to fetch the user'

    def test_create_client(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new client
        following a DAR approval. The creation includes 2 steps:
            - Create the client
            - Update the client-wide permission evaluation policy
                which can't be done at creation time
        Here we simulate the failure of the former
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                URLS["client"],
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_client('some_client', 60)
            assert exc.value.details == 'Failed to create a project'

    def test_create_client_update(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new client
        following a DAR approval. The creation includes 2 steps:
            - Create the client
            - Update the client-wide permission evaluation policy
                which can't be done at creation time
        Here we simulate the failure of the latter
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            # get client id
            rsps.add(
                responses.GET,
                URLS["client"] + '?clientId=some_client',
                json=[{"id": 12}],
                status=201
            )
            # create client
            rsps.add(
                responses.POST,
                URLS["client"],
                status=201
            )
            rsps.add(
                responses.PUT,
                URLS["client_auth"] % '12',
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_client('some_client', 60)
            assert exc.value.details == 'Failed to create a project'

    def test_create_scope(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new scope
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                URLS["scopes"] % kc_client.client_id,
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_scope('some_scope')
            assert exc.value.details == 'Failed to create a project\'s scope'

    def test_create_policy(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new policy
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                (URLS["policies"] % kc_client.client_id) + '/user',
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_policy({'name': 'some_policy'}, '/user')
            assert exc.value.details == 'Failed to create a project\'s policy'

    def test_create_resource(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new resource
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                URLS["resource"] % kc_client.client_id,
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_resource({'name': 'some_resource'})
            assert exc.value.details == 'Failed to create a project\'s resource'

    def test_create_permission(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new permission
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                URLS["permission"] % kc_client.client_id,
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_permission({'name': 'some_permission'})
            assert exc.value.details == 'Failed to create a project\'s permission'

    def test_create_user(
            self
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new user
        """
        kc_client = Keycloak()
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                URLS["roles"] + "/Users",
                json={"name": "Users"},
                status=200
            )
            rsps.add(
                responses.POST,
                URLS["user"],
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                kc_client.create_user(**{'email': 'some@email.com'})
            assert exc.value.details == 'Failed to create the user'
