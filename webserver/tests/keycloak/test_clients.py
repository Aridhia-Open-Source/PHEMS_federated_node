import httpx
from pytest import mark, raises
import responses
from responses import matchers
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakClients(TestKeycloakMixin):
    """
    """
    @mark.asyncio
    async def test_create_client(
            self, keycloak_login_request_mock, respx_mock
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
        kc_client = await Keycloak.create()
        respx_mock.post(
            URLS["client"]
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.create_client('some_client', 60)
        assert exc.value.description == 'Failed to create a project'

    @mark.asyncio
    async def test_create_client_update(
            self, keycloak_login_request_mock, respx_mock
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
        kc_client = await Keycloak.create()
        # get client id
        respx_mock.get(
            URLS["client"],
            params={"clientId": "some_client"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": 12}],
                status_code=201
            )
        )
        # create client
        respx_mock.post(
            URLS["client"]
        ).mock(
            return_value=httpx.Response(
                status_code=201
            )
        )
        respx_mock.put(
            URLS["client_auth"] % 12
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.create_client('some_client', 60)
        assert exc.value.description == 'Failed to create a project'

    @mark.asyncio
    async def test_get_client_id(self, keycloak_login_request_mock, respx_mock):
        """
        Test that the proper exception is raised when the
        keycloak API returns != 200 on fetching a client id.
        Usually invoked during the class init
        """
        respx_mock.get(
            URLS["client"],
            params={"clientId": "global"}
        ).mock(
            return_value=httpx.Response(
                json=self.common_error_response,
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await Keycloak.create()
        assert exc.value.description == 'Could not find client'

    @mark.asyncio
    async def test_get_client_id_fails(self, keycloak_login_request_mock, respx_mock):
        """
        Test that the proper exception is raised when the
        keycloak API is successful, but no entries are returned
        on fetching a client id. Usually invoked during the class init
        """
        respx_mock.get(
            URLS["client"],
            params={"clientId": "global"}
        ).mock(
            return_value=httpx.Response(
                json=[],
                status_code=200
            )
        )
        with raises(KeycloakError) as exc:
            await Keycloak.create()
        assert exc.value.description == 'Could not find project'

    @mark.asyncio
    async def test_enable_token_exchange(self, keycloak_login_request_mock, respx_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = await Keycloak.create()
        # Enable client exchange
        respx_mock.put(
            URLS["client_exchange"] % kc_client.client_id
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        # realm-management client fetch
        respx_mock.get(
            URLS["client"],
            params={"clientId": "realm-management"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "rm_id"}],
                status_code=200
            )
        )
        # token-exchange scope
        respx_mock.get(
            URLS["scopes"] % "rm_id",
            params={
                "permission": False,
                "name": "token-exchange"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "scope_id"}],
                status_code=200
            )
        )
        # get realm management resource
        respx_mock.get(
            URLS["resource"] % "rm_id",
            params={
                "name": f"client.resource.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "exchange_res_id"}],
                status_code=200
            )
        )
        # create custom policy
        respx_mock.post(
            (URLS["policies"] % "rm_id") + "/client",
        ).mock(
            return_value=httpx.Response(
                json={"id": "exchange_policy_id"},
                status_code=201
            )
        )
        # get permission
        respx_mock.get(
            URLS["permission"] % "rm_id",
            params={
                "name": f"token-exchange.permission.client.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "exchange_permission_id"}],
                status_code=200
            )
        )
        # update permission
        respx_mock.put(
            (URLS["permission"] % "rm_id") + "/exchange_permission_id"
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        await kc_client.enable_token_exchange()

    @mark.asyncio
    async def test_enable_token_exchange_policy_exchange_exists(self, keycloak_login_request_mock, respx_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = await Keycloak.create()
        # Enable client exchange
        respx_mock.put(
            URLS["client_exchange"] % kc_client.client_id
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        # realm-management client fetch
        respx_mock.get(
            URLS["client"],
            params={"clientId": "realm-management"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "rm_id"}],
                status_code=200
            )
        )
        # token-exchange scope
        respx_mock.get(
            URLS["scopes"] % "rm_id",
            params={
                "permission": False,
                "name": "token-exchange"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "scope_id"}],
                status_code=200
            )
        )
        # get realm management resource
        respx_mock.get(
            URLS["resource"] % "rm_id",
            params={
                "name": f"client.resource.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "exchange_res_id"}],
                status_code=200
            )
        )
        # create custom policy
        respx_mock.post(
            (URLS["policies"] % "rm_id") + "/client",
        ).mock(
            return_value=httpx.Response(
                status_code=409
            )
        )
        # fetch custom policy
        respx_mock.get(
            (URLS["policies"] % "rm_id") + "/client",
            params={"name": "token-exchange-global"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "exchange_policy_id"}],
                status_code=200
            )
        )
        # get permission
        respx_mock.get(
            URLS["permission"] % "rm_id",
            params={
                "name": f"token-exchange.permission.client.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "exchange_permission_id"}],
                status_code=200
            )
        )
        # update permission
        respx_mock.put(
            (URLS["permission"] % "rm_id") + "/exchange_permission_id"
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        await kc_client.enable_token_exchange()

    @mark.asyncio
    async def test_enable_token_exchange_policy_exchange_fails(self, keycloak_login_request_mock, respx_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = await Keycloak.create()
        respx_mock.put(
            URLS["client_exchange"] % kc_client.client_id
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        # realm-management client fetch
        respx_mock.get(
            URLS["client"],
            params={"clientId": "realm-management"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "rm_id"}],
                status_code=200
            )
        )
        # token-exchange scope
        respx_mock.get(
            URLS["scopes"] % "rm_id",
            params={
                "permission": False,
                "name": "token-exchange"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "scope_id"}],
                status_code=200
            )
        )
        # get realm management resource
        respx_mock.get(
            URLS["resource"] % "rm_id",
            params={
                "name": f"client.resource.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "exchange_res_id"}],
                status_code=200
            )
        )
        # create custom policy
        respx_mock.post(
            (URLS["policies"] % "rm_id") + "/client",
        ).mock(
            return_value=httpx.Response(
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.enable_token_exchange()
        assert exc.value.description == 'Something went wrong in creating the set of permissions on Keycloak'

    @mark.asyncio
    async def test_enable_token_exchange_policy_exchange_patch_fails(self, keycloak_login_request_mock, respx_mock):
        """
        enable_token_exchange returns nothing, just chains few keycloak
        API calls. If any fails with status code != 409, should raise
        a custom exception
        """
        kc_client = await Keycloak.create()
        # Enable client exchange
        respx_mock.put(
            URLS["client_exchange"] % kc_client.client_id
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        # realm-management client fetch
        respx_mock.get(
            URLS["client"],
            params={"clientId": "realm-management"}
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "rm_id"}],
                status_code=200
            )
        )
        # token-exchange scope
        respx_mock.get(
            URLS["scopes"] % "rm_id",
            params={
                "permission": False,
                "name": "token-exchange"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "scope_id"}],
                status_code=200
            )
        )
        # get realm management resource
        respx_mock.get(
            URLS["resource"] % "rm_id",
            params={
                "name": f"client.resource.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"_id": "exchange_res_id"}],
                status_code=200
            )
        )
        # create custom policy
        respx_mock.post(
            (URLS["policies"] % "rm_id") + "/client",
        ).mock(
            return_value=httpx.Response(
                json={"id": "exchange_policy_id"},
                status_code=201
            )
        )
        # get permission
        respx_mock.get(
            URLS["permission"] % "rm_id",
            params={
                "name": f"token-exchange.permission.client.{kc_client.client_id}"
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "exchange_permission_id"}],
                status_code=200
            )
        )
        # update permission
        respx_mock.put(
            (URLS["permission"] % "rm_id") + "/exchange_permission_id"
        ).mock(
            return_value=httpx.Response(
                status_code=500
            )
        )
        with raises(KeycloakError) as exc:
            await kc_client.enable_token_exchange()
        assert exc.value.description == 'Failed to update the exchange permission'
