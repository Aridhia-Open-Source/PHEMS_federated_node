import pytest
import responses
from responses import matchers
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakClients(TestKeycloakMixin):
    """
    """
    def test_create_client(
            self, keycloak_login_request_mock
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
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["client"],
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.create_client('some_client', 60)
        assert exc.value.description == 'Failed to create a project'

    def test_create_client_update(
            self, keycloak_login_request_mock
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
        # get client id
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["client"] + '?clientId=some_client',
            json=[{"id": 12}],
            status=201
        )
        # create client
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["client"],
            status=201
        )
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["client_auth"] % '12',
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.create_client('some_client', 60)
        assert exc.value.description == 'Failed to create a project'

    def test_get_client_id(self):
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
                URLS["client"],
                match=[matchers.query_string_matcher("clientId=global")],
                json=self.common_error_response,
                status=500
            )
            with pytest.raises(KeycloakError) as exc:
                Keycloak()
            assert exc.value.description == 'Could not find client'

    def test_get_client_id_fails(self):
        """
        Test that the proper exception is raised when the
        keycloak API is successful, but no entries are returned
        on fetching a client id. Usually invoked during the class init
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
                URLS["client"],
                match=[matchers.query_string_matcher("clientId=global")],
                json=[]
            )
            with pytest.raises(KeycloakError) as exc:
                Keycloak()
            assert exc.value.description == 'Could not find project'

    def test_enable_token_exchange(self, keycloak_login_request_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = Keycloak()
        # Enable client exchange
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["client_exchange"] % kc_client.client_id,
        )
        # realm-management client fetch
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["client"],
            json=[{"id": "rm_id"}],
            match=[matchers.query_string_matcher("clientId=realm-management")],
        )
        # token-exchange scope
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["scopes"] % "rm_id",
            json=[{"id": "scope_id"}],
            match=[matchers.query_string_matcher("permission=False&name=token-exchange")],
        )
        # get realm management resource
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["resource"] % "rm_id",
            json=[{"_id": "exchange_res_id"}],
            match=[matchers.query_string_matcher(f"name=client.resource.{kc_client.client_id}")],
        )
        # create custom policy
        keycloak_login_request_mock.add(
            responses.POST,
            (URLS["policies"] % "rm_id") + "/client",
            json={"id": "exchange_policy_id"}
        )
        # get permission
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["permission"] % "rm_id",
            json=[{"id": "exchange_permission_id"}],
            match=[matchers.query_string_matcher(f"name=token-exchange.permission.client.{kc_client.client_id}")],
        )
        # update permission
        keycloak_login_request_mock.add(
            responses.PUT,
            (URLS["permission"] % "rm_id") + "/exchange_permission_id"
        )
        kc_client.enable_token_exchange()

    def test_enable_token_exchange_policy_exchange_exists(self, keycloak_login_request_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = Keycloak()
        # Enable client exchange
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["client_exchange"] % kc_client.client_id,
        )
        # realm-management client fetch
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["client"],
            json=[{"id": "rm_id"}],
            match=[matchers.query_string_matcher("clientId=realm-management")],
        )
        # token-exchange scope
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["scopes"] % "rm_id",
            json=[{"id": "scope_id"}],
            match=[matchers.query_string_matcher("permission=False&name=token-exchange")],
        )
        # get realm management resource
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["resource"] % "rm_id",
            json=[{"_id": "exchange_res_id"}],
            match=[matchers.query_string_matcher(f"name=client.resource.{kc_client.client_id}")],
        )
        # create custom policy
        keycloak_login_request_mock.add(
            responses.POST,
            (URLS["policies"] % "rm_id") + "/client",
            status=409
        )
        # fetch custom policy
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["policies"] % "rm_id") + "/client",
            status=200,
            match=[matchers.query_string_matcher(f"name=token-exchange-global")],
            json=[{"id": "exchange_policy_id"}]
        )
        # get permission
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["permission"] % "rm_id",
            json=[{"id": "exchange_permission_id"}],
            match=[matchers.query_string_matcher(f"name=token-exchange.permission.client.{kc_client.client_id}")],
        )
        # update permission
        keycloak_login_request_mock.add(
            responses.PUT,
            (URLS["permission"] % "rm_id") + "/exchange_permission_id"
        )
        kc_client.enable_token_exchange()

    def test_enable_token_exchange_policy_exchange_fails(self, keycloak_login_request_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = Keycloak()
        # Enable client exchange
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["client_exchange"] % kc_client.client_id,
        )
        # realm-management client fetch
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["client"],
            json=[{"id": "rm_id"}],
            match=[matchers.query_string_matcher("clientId=realm-management")],
        )
        # token-exchange scope
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["scopes"] % "rm_id",
            json=[{"id": "scope_id"}],
            match=[matchers.query_string_matcher("permission=False&name=token-exchange")],
        )
        # get realm management resource
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["resource"] % "rm_id",
            json=[{"_id": "exchange_res_id"}],
            match=[matchers.query_string_matcher(f"name=client.resource.{kc_client.client_id}")],
        )
        # create custom policy
        keycloak_login_request_mock.add(
            responses.POST,
            (URLS["policies"] % "rm_id") + "/client",
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.enable_token_exchange()
        assert exc.value.description == 'Something went wrong in creating the set of permissions on Keycloak'

    def test_enable_token_exchange_policy_exchange_patch_fails(self, keycloak_login_request_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = Keycloak()
        # Enable client exchange
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["client_exchange"] % kc_client.client_id,
        )
        # realm-management client fetch
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["client"],
            json=[{"id": "rm_id"}],
            match=[matchers.query_string_matcher("clientId=realm-management")],
        )
        # token-exchange scope
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["scopes"] % "rm_id",
            json=[{"id": "scope_id"}],
            match=[matchers.query_string_matcher("permission=False&name=token-exchange")],
        )
        # get realm management resource
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["resource"] % "rm_id",
            json=[{"_id": "exchange_res_id"}],
            match=[matchers.query_string_matcher(f"name=client.resource.{kc_client.client_id}")],
        )
        # create custom policy
        keycloak_login_request_mock.add(
            responses.POST,
            (URLS["policies"] % "rm_id") + "/client",
            status=409
        )
        # fetch custom policy
        keycloak_login_request_mock.add(
            responses.GET,
            (URLS["policies"] % "rm_id") + "/client",
            status=200,
            match=[matchers.query_string_matcher(f"name=token-exchange-global")],
            json=[{"id": "exchange_policy_id"}]
        )
        # get permission
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["permission"] % "rm_id",
            json=[{"id": "exchange_permission_id"}],
            match=[matchers.query_string_matcher(f"name=token-exchange.permission.client.{kc_client.client_id}")],
        )
        # update permission
        keycloak_login_request_mock.add(
            responses.PUT,
            (URLS["permission"] % "rm_id") + "/exchange_permission_id",
            status=500,
            json=self.common_error_response,
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.enable_token_exchange()
        assert exc.value.description == 'Failed to update the exchange permission'
