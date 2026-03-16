import httpx
from pytest_asyncio import fixture
from pytest import mark, raises
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
    def keycloak_login_request_mock(self, respx_mock, admin_user, admin_user_uuid, new_user):
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'admin-cli',
                'grant_type': 'password',
                'username': 'admin',
                'password': 'password1'
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "token", "refresh_token": "ref_token"},
                status_code=200
            )
        )
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'global',
                'client_secret': 'clientsecret',
                'grant_type': 'password',
                'username': 'admin',
                'password': 'password1'
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "token", "refresh_token": "ref_token"},
                status_code=200
            )
        )
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'global',
                'client_secret': 'clientsecret',
                'grant_type': 'refresh_token',
                'refresh_token': 'admin_token'
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "token", "refresh_token": "ref_token"},
                status_code=200
            )
        )
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'client_id': 'global',
                'client_secret': 'clientsecret',
                'grant_type': 'refresh_token',
                'refresh_token': 'user_refresh_token'
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "user_token", "refresh_token": "user_ref_token"},
                status_code=200
            )
        )
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:uma-ticket',
                'audience': 'global',
                'response_mode': 'decision',
                'permission': 'resid#can_do_admin'
            }
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        respx_mock.get(
            URLS["client"],
            params={"clientId": "global"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "clientid"}],
                status_code=200
            )
        )
        respx_mock.get(
            URLS["client_secret"] % "clientid",
        ).mock(
            return_value=httpx.Response(
                json={"value": "clientsecret"},
                status_code=200
            )
        )
        respx_mock.get(
            URLS["resource"] % "clientid",
            params={"name": "endpoints"}
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "resid"}],
                status_code=200
            )
        )
        respx_mock.get(
            URLS["resource"] % "clientid",
            params={"name": "1-testds"}
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "resid"}],
                status_code=200
            )
        )
        respx_mock.get(
            URLS["user"] + f"/{admin_user_uuid}",
        ).mock(
            return_value=httpx.Response(
                json=admin_user,
                status_code=200
            )
        )
        respx_mock.get(
            URLS["user"] + f"/{new_user["id"]}",
        ).mock(
            return_value=httpx.Response(
                json=new_user,
                status_code=200
            )
        )
        respx_mock.get(
            URLS["user_role"] % admin_user_uuid,
        ).mock(
            return_value=httpx.Response(
                json=[{"name": "User"}],
                status_code=200
            )
        )
        respx_mock.get(
            URLS["user_role"] % new_user["id"],
        ).mock(
            return_value=httpx.Response(
                json=[{"name": "User"}],
                status_code=200
            )
        )
        respx_mock.get(
            URLS["roles"] + "/Users",
        ).mock(
            return_value=httpx.Response(
                json=[{"name": "User"}],
                status_code=200
            )
        )


class TestKeycloakResponseFailures(TestKeycloakMixin):
    @mark.asyncio
    async def test_exchange_global_token_access_token(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on access_token fetching
        """
        kc_client: Keycloak = await Keycloak.create()
        # Mocking the requests for the specific token
        respx_mock.post(
            URLS["get_token"],
        ).mock(
            return_value=httpx.Response(
                json={"error": "Invalid credentials"},
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.exchange_global_token('not a token')
        assert exc.value.description == 'Cannot get an access token'

    @mark.asyncio
    async def test_exchange_global_token(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on token exchange
        """
        kc_client = await Keycloak.create()
        # Mock the request in the order they are submitted.
        # Unfortunately the match param doesn't detect form data
        respx_mock.post(URLS["get_token"]).mock(
            side_effect=[
                httpx.Response(
                    json={"access_token": "random token"},
                    status_code=200
                ),
                httpx.Response(
                    json=self.common_error_response,
                    status_code=500
                )
            ]
        )
        with raises(KeycloakError) as exc:
            await kc_client.exchange_global_token('not a token')
        assert exc.value.description == 'Cannot exchange token'

    @mark.asyncio
    async def test_impersonation_token(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on impersonation token
        """
        kc_client = await Keycloak.create()
        # Mocking self.get_admin_token_global() request to be successful
        respx_mock.post(URLS["get_token"]).mock(
            side_effect=[
                httpx.Response(
                    json={"access_token": "random token"},
                    status_code=200
                ),
                httpx.Response(
                    json=self.common_error_response,
                    status_code=500
                )
            ]
        )
        with raises(KeycloakError) as exc:
            await kc_client.get_impersonation_token('some user id')
        assert exc.value.description == 'Cannot exchange impersonation token'

    @mark.asyncio
    async def test_get_client_secret(self, keycloak_login_request_mock, respx_mock):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on fetching the client secret
        """
        kc_client = await Keycloak.create()
        # Mocking self.get_admin_token_global() request to be successful
        respx_mock.get(
            URLS["client_secret"] % kc_client.client_id
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client._get_client_secret()
        assert exc.value.description == f'Failed to fetch {kc_client.client_id}\'s secret'

    @mark.asyncio
    async def test_get_role(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific role
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["roles"] + "/some_role"
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.get_role('some_role')
        assert exc.value.description == 'Failed to fetch roles'

    @mark.asyncio
    async def test_get_resource(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific permission
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["resource"] % kc_client.client_id,
            params={"name": "some_resource"}
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "resource_id"}],
                status_code=200
            )
        )
        await kc_client.get_resource('some_resource')

    @mark.asyncio
    async def test_get_resource_empty_list_fails(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that no exception is raised when the
        keycloak API is successful but no match is returned in the results list
        on getting a specific permission
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["resource"] % kc_client.client_id,
            params={"name": "some_resource"}
        ).mock(
            return_value=httpx.Response(
                json=[],
                status_code=200
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.get_resource('some_resource')
        assert exc.value.description == 'Failed to fetch the resource'

    @mark.asyncio
    async def test_get_resource_fails(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on getting a specific permission
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["resource"] % kc_client.client_id,
            params={"name": "some_resource"}
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.get_resource('some_resource')
        assert exc.value.description == 'Failed to fetch the resource'

    @mark.asyncio
    async def test_create_resource(
            self, keycloak_login_request_mock, respx_mock
    ):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on creating a new resource
        """
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["resource"] % kc_client.client_id
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.create_resource({'name': 'some_resource'})
        assert exc.value.description == 'Failed to create a project\'s resource'

    @mark.asyncio
    async def test_patch_resource(self, keycloak_login_request_mock, respx_mock):
        """
        patch_resource does not return an object, only ensures
        the keycloak API call is successful.
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["resource"] % kc_client.client_id,
            params={"name": "some_resource"}
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "resource_id"}],
                status_code=200
            )
        )
        respx_mock.put(
            (URLS["resource"] % kc_client.client_id) + "/resource_id"
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "resource_id"}],
                status_code=200
            )
        )
        await kc_client.patch_resource("some_resource", **{"name": "new_name"})

    @mark.asyncio
    async def test_patch_resource_fails(self, keycloak_login_request_mock, respx_mock):
        """
        patch_resource does not return an object, only ensures
        a custom exception is raised if the keycloak API call fails
        """
        kc_client = await Keycloak.create()
        respx_mock.get(
            URLS["resource"] % kc_client.client_id,
            params={"name": "some_resource"}
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "resource_id"}],
                status_code=200
            )
        )
        respx_mock.put(
            (URLS["resource"] % kc_client.client_id) + "/resource_id"
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.patch_resource("some_resource", **{"name": "new_name"})
        assert exc.value.description == 'Failed to patch the resource'
