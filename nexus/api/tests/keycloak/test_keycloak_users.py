import pytest
import responses
from responses import matchers
import urllib.parse

from app.helpers.exceptions import AuthenticationError, KeycloakError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakUsers(TestKeycloakMixin):
    """
    Collection of tests for keycloak users.
      Split from the rest to improve maintainability
    """
    email = 'user@email.com'
    email_url = urllib.parse.quote_plus('user@email.com')
    user_id = "447dbf78-4ca0-4028-9c50-64acc19cb0c3"

    def get_new_user_api_resp(self) -> list[dict[str, str]]:
        return [{"username": self.email, "id": self.user_id}]

    def test_list_users(
        self, keycloak_login_request_mock
    ):
        """
        Test that the user is created properly
        """
        kc_client = Keycloak()
        expected_out = self.get_new_user_api_resp()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=expected_out,
            status=200
        )
        user_info = kc_client.list_users()
        assert expected_out == user_info

    def test_list_users_fails(
        self, keycloak_login_request_mock
    ):
        """
        Test that the user is created properly
        """
        kc_client = Keycloak()
        expected_out = self.get_new_user_api_resp()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=expected_out,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.list_users()

        assert exc.value.description == "Failed to fetch the users"

    def test_get_user(
        self, keycloak_login_request_mock
    ):
        """
        Test that the user is fetched by the username
        """
        kc_client = Keycloak()
        expected_out = self.get_new_user_api_resp()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=[expected_out],
            match=[matchers.query_string_matcher(f"username={self.email_url}&exact=True")],
            status=200
        )
        user_info = kc_client.get_user(self.email)
        assert expected_out == user_info

    def test_get_user_with_email(
        self, keycloak_login_request_mock
    ):
        """
        Test that the user is fetched with their email
        """
        kc_client = Keycloak()
        expected_out = self.get_new_user_api_resp()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=[],
            match=[matchers.query_string_matcher(f"username={self.email_url}&exact=True")],
            status=200
        )
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=[expected_out],
            match=[matchers.query_string_matcher(f"email={self.email_url}&exact=True")],
            status=200
        )
        user_info = kc_client.get_user(self.email)
        assert expected_out == user_info

    def test_get_user_fails(
        self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a user by its username
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=self.common_error_response,
            match=[matchers.query_string_matcher(f"username={self.email_url}&exact=True")],
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.get_user(self.email)
        assert exc.value.description == 'Failed to fetch the user'

    def test_create_user(
            self, keycloak_login_request_mock
    ):
        """
        Test that the user is created
        """
        kc_client = Keycloak()
        user_list = self.get_new_user_api_resp()

        keycloak_login_request_mock.add(
            responses.GET,
            URLS["roles"] + "/Users",
            json={"name": "Users"},
            status=200
        )
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user"],
            json=user_list,
            match=[matchers.query_string_matcher(f"username={self.email_url}&exact=True")],
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["user_role"] % self.user_id,
            json=[{"name": "User"}],
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["user"],
            json=self.common_error_response,
            status=200
        )
        user_info = kc_client.create_user(**{'email': self.email})
        assert "password" in user_info

    def test_create_user_fails(
            self, keycloak_login_request_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new user
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["roles"] + "/Users",
            json={"name": "Users"},
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["user"],
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.create_user(**{'email': self.email})
        assert exc.value.description == 'Failed to create the user'

    def test_get_user_role(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.get_user_role
        behaves as expected
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user_role"] % self.user_id,
            json=[{"name": "Users"}],
            status=200
        )
        res = kc_client.get_user_role(self.user_id)
        assert isinstance(res, list)
        assert ["Users"] == res

    def test_get_user_role_fails(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.get_user_role
        handles failures as expected
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.GET,
            URLS["user_role"] % self.user_id,
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.get_user_role(self.user_id)
        assert exc.value.description == 'Failed to get the user\'s role'

    def test_assign_role_to_user(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.assign_role_to_user
        behaves as expected. It returns none, so we expect no
        exceptions to be raised
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.POST,
            f"{URLS["roles"]}/Users",
            json={"id": "role_id"},
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["user_role"] % self.user_id,
            status=200
        )
        kc_client.assign_role_to_user(self.user_id, "Users")

    def test_assign_role_to_user_fails(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.assign_role_to_user
        handles failures as expected
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.POST,
            f"{URLS["roles"]}/Users",
            json={"id": "role_id"},
            status=200
        )
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["user_role"] % self.user_id,
            status=400
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.assign_role_to_user(self.user_id, "Users")
        assert exc.value.description == 'Failed to create the user'

    def test_reset_user_pass(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.reset_user_pass
        behaves as expected. Nothing is returned
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json={"error_description": "Account is not fully set up"},
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'global',
                        'client_secret': 'clientsecret',
                        'grant_type': 'password',
                        'username': self.email,
                        'password': 'pass'
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=401
        )
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["user_reset"] % self.user_id,
            status=200
        )
        kc_client.reset_user_pass(self.user_id, self.email, "pass", "new_pas")

    def test_reset_user_pass_incorrect_temp_pass(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.reset_user_pass
        handles failures as expected
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json={"error_description": "Unauthorized"},
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'global',
                        'client_secret': 'clientsecret',
                        'grant_type': 'password',
                        'username': self.email,
                        'password': 'pass'
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=401
        )
        with pytest.raises(AuthenticationError) as exc:
            kc_client.reset_user_pass(self.user_id, self.email, "pass", "new_pas")
        assert exc.value.description == 'Incorrect credentials'

    def test_reset_user_pass_fails(
            self, keycloak_login_request_mock
    ):
        """
        Simple test to make sure keycloak.reset_user_pass
        handles failures as expected
        """
        kc_client = Keycloak()
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["get_token"],
            json={"error_description": "Account is not fully set up"},
            match=[matchers.urlencoded_params_matcher(
                    {
                        'client_id': 'global',
                        'client_secret': 'clientsecret',
                        'grant_type': 'password',
                        'username': self.email,
                        'password': 'pass'
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ],
            status=401
        )
        keycloak_login_request_mock.add(
            responses.PUT,
            URLS["user_reset"] % self.user_id,
            json=self.common_error_response,
            status=500
        )
        with pytest.raises(KeycloakError) as exc:
            kc_client.reset_user_pass(self.user_id, self.email, "pass", "new_pas")
        assert exc.value.description == 'Could not update the password.'

    def test_is_user_admin(self, keycloak_login_request_mock):
        """
        Simplistic is_user_admin test to verify if all API requests succeeds
        no exception is raised
        """
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["validate"],
            json={"realm_access": {"roles": ["Administrator", "Users"]}},
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ]
        )
        assert Keycloak().is_user_admin("token")

    def test_is_user_admin_normal_user(self, keycloak_login_request_mock):
        """
        Simplistic is_user_admin test to verify if all API requests succeeds
        no exception is raised
        """
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["validate"],
            json={"realm_access": {"roles": ["Users"]}},
            match=[
                matchers.urlencoded_params_matcher(
                    {
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "token": "token"
                    }
                ),
                matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})
            ]
        )
        assert not Keycloak().is_user_admin("token")

    def test_is_user_admin_token_expired(self, keycloak_login_request_mock):
        """
        Simplistic is_user_admin test to verify if all API requests fails
        the Authentication exception is raised
        """
        keycloak_login_request_mock.add(
            responses.POST,
            URLS["validate"],
            json={"realm_access": {"roles": ["Users"]}},
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
            status=401
        )
        with pytest.raises(AuthenticationError) as exc:
            Keycloak().is_user_admin("token")
        assert exc.value.description == 'Failed to login'

