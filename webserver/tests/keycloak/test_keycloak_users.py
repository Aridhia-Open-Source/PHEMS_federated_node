import httpx
from pytest import mark, raises
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

    @mark.asyncio
    async def test_list_users(
        self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the user is created properly
        """
        kc_client = await Keycloak.create()
        expected_out = self.get_new_user_api_resp()
        respx_mock.get(
            URLS["user"],
        ).mock(
            return_value=httpx.Response(
                json=expected_out,
                status_code=200
            )
        )
        user_info = await kc_client.list_users()
        assert expected_out == user_info

    @mark.asyncio
    async def test_list_users_fails(
        self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the user creation failure is handled properly by
        raising internal Exception
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["user"],
        ).mock(
            return_value=httpx.Response(
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.list_users()

        assert exc.value.description == "Failed to fetch the users"

    @mark.asyncio
    async def test_get_user(
        self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the user is fetched by the username
        """
        kc_client = await Keycloak.create()
        expected_out = self.get_new_user_api_resp()
        respx_mock.get(
            URLS["user"],
            params={
                "username": self.email,
                "exact": True
            }
        ).mock(
            return_value=httpx.Response(
                json=[expected_out],
                status_code=200
            )
        )
        user_info = await kc_client.get_user(self.email)
        assert expected_out == user_info

    @mark.asyncio
    async def test_get_user_with_email(
        self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the user is fetched with their email
        """
        kc_client = await Keycloak.create()
        expected_out = self.get_new_user_api_resp()
        respx_mock.get(
            URLS["user"],
            params={
                "username": self.email,
                "exact": True
            }
        ).mock(
            return_value=httpx.Response(
                json=[],
                status_code=200
            )
        )
        respx_mock.get(
            URLS["user"],
            params={
                "email": self.email,
                "exact": True
            }
        ).mock(
            return_value=httpx.Response(
                json=[expected_out],
                status_code=200
            )
        )
        user_info = await kc_client.get_user(self.email)
        assert expected_out == user_info

    @mark.asyncio
    async def test_get_user_fails(
        self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a user by its username
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["user"],
            params={
                "username": self.email,
                "exact": True
            }
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.get_user(self.email)
        assert exc.value.description == 'Failed to fetch the user'

    @mark.asyncio
    async def test_create_user(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the user is created
        """
        kc_client = await Keycloak.create()
        user_list = self.get_new_user_api_resp()

        respx_mock.get(
            URLS["roles"] + "/Users"
        ).mock(
            return_value=httpx.Response(
                json={"name": "Users"},
                status_code=200
            )
        )
        respx_mock.get(
            URLS["user"],
            params={
                "username": self.email,
                "exact": True
            }
        ).mock(
            return_value=httpx.Response(
                json=user_list,
                status_code=200
            )
        )
        respx_mock.post(
            URLS["user_role"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                json=[{"name": "User"}],
                status_code=200
            )
        )
        respx_mock.post(
            URLS["user"]
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        user_info = await kc_client.create_user(**{'email': self.email})
        assert "password" in user_info

    @mark.asyncio
    async def test_create_user_fails(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new user
        """
        kc_client = await Keycloak.create()

        respx_mock.get(
            URLS["roles"] + "/Users"
        ).mock(
            return_value=httpx.Response(
                json={"name": "Users"},
                status_code=200
            )
        )
        respx_mock.post(
            URLS["user"]
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.create_user(**{'email': self.email})
        assert exc.value.description == 'Failed to create the user'

    @mark.asyncio
    async def test_get_user_role(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.get_user_role
        behaves as expected
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["user_role"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                json=[{"name": "Users"}],
                status_code=200
            )
        )
        res = await kc_client.get_user_role(self.user_id)
        assert isinstance(res, list)
        assert ["Users"] == res

    @mark.asyncio
    async def test_get_user_role_fails(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.get_user_role
        handles failures as expected
        """
        kc_client = await Keycloak.create()

        respx_mock.get(
            URLS["user_role"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.get_user_role(self.user_id)
        assert exc.value.description == 'Failed to get the user\'s role'

    @mark.asyncio
    async def test_assign_role_to_user(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.assign_role_to_user
        behaves as expected. It returns none, so we expect no
        exceptions to be raised
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["roles"] + "/Users"
        ).mock(
            return_value=httpx.Response(
                json={"id": "role_id"},
                status_code=201
            )
        )
        respx_mock.post(
            URLS["user_role"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                status_code=201
            )
        )
        await kc_client.assign_role_to_user(self.user_id, "Users")

    @mark.asyncio
    async def test_assign_role_to_user_fails(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.assign_role_to_user
        handles failures as expected
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["roles"] + "/Users"
        ).mock(
            return_value=httpx.Response(
                json={"id": "role_id"},
                status_code=201
            )
        )
        respx_mock.post(
            URLS["user_role"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.assign_role_to_user(self.user_id, "Users")
        assert exc.value.description == 'Failed to create the user'

    @mark.asyncio
    async def test_reset_user_pass(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.reset_user_pass
        behaves as expected. Nothing is returned
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'global',
                'client_secret': 'clientsecret',
                'grant_type': 'password',
                'username': self.email,
                'password': 'pass'
            }
        ).mock(
            return_value=httpx.Response(
                json={"error_description": "Account is not fully set up"},
                status_code=401
            )
        )
        respx_mock.put(
            URLS["user_reset"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                status_code=201
            )
        )
        await kc_client.reset_user_pass(self.user_id, self.email, "pass", "new_pas")

    @mark.asyncio
    async def test_reset_user_pass_incorrect_temp_pass(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.reset_user_pass
        handles failures as expected
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'global',
                'client_secret': 'clientsecret',
                'grant_type': 'password',
                'username': self.email,
                'password': 'pass'
            }
        ).mock(
            return_value=httpx.Response(
                json={"error_description": "Unauthorized"},
                status_code=401
            )
        )
        with raises(AuthenticationError) as exc:
            await kc_client.reset_user_pass(self.user_id, self.email, "pass", "new_pas")
        assert exc.value.description == 'Incorrect credentials'

    @mark.asyncio
    async def test_reset_user_pass_fails(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Simple test to make sure keycloak.reset_user_pass
        handles failures as expected
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'global',
                'client_secret': 'clientsecret',
                'grant_type': 'password',
                'username': self.email,
                'password': 'pass'
            }
        ).mock(
            return_value=httpx.Response(
                json={"error_description": "Account is not fully set up"},
                status_code=401
            )
        )
        respx_mock.put(
            URLS["user_reset"] % self.user_id
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.reset_user_pass(self.user_id, self.email, "pass", "new_pas")
        assert exc.value.description == 'Could not update the password.'

    @mark.asyncio
    async def test_is_user_admin(self, keycloak_login_request_mock, respx_mock):
        """
        Simplistic is_user_admin test to verify if all API requests succeeds
        no exception is raised
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["validate"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_secret": "clientsecret",
                "client_id": "global",
                "token": "token"
            }
        ).mock(
            return_value=httpx.Response(
                json={"realm_access": {"roles": ["Administrator", "Users"]}},
                status_code=200
            )
        )
        assert await kc_client.is_user_admin("token")

    @mark.asyncio
    async def test_is_user_admin_normal_user(self, keycloak_login_request_mock, respx_mock):
        """
        Simplistic is_user_admin test to verify if all API requests succeeds
        no exception is raised
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["validate"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_secret": "clientsecret",
                "client_id": "global",
                "token": "token"
            }
        ).mock(
            return_value=httpx.Response(
                json={"realm_access": {"roles": ["Users"]}},
                status_code=200
            )
        )
        assert not await kc_client.is_user_admin("token")

    @mark.asyncio
    async def test_is_user_admin_token_expired(self, keycloak_login_request_mock, respx_mock):
        """
        Simplistic is_user_admin test to verify if all API requests fails
        the Authentication exception is raised
        """
        respx_mock.post(
            URLS["validate"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_secret": "clientsecret",
                "client_id": "global",
                "token": "token"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        kc_client = await Keycloak.create()
        with raises(AuthenticationError) as exc:
            await kc_client.is_user_admin("token")
        assert exc.value.description == 'Failed to login'

