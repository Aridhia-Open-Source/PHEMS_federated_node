import pytest
import responses
from responses import matchers
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakClients(TestKeycloakMixin):
    """
    """
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
