import httpx
from pytest import mark, raises
import responses
from responses import matchers

from app.helpers.exceptions import UnauthorizedError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakTokens(TestKeycloakMixin):
    """
    """
    @mark.asyncio
    async def test_check_permissions(self, keycloak_login_request_mock, respx_mock, mocker):
        mocker.patch.object(Keycloak, "get_resource", return_value={"_id": "resource"})
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
                "audience": "global",
                "response_mode": "decision",
                'permission': 'resource#can_admin_dataset'
            }
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.check_permissions("token", "can_admin_dataset", "resource", is_access_token=True)

    @mark.asyncio
    async def test_check_permissions_fails(self, keycloak_login_request_mock, respx_mock, mocker):
        mocker.patch.object(Keycloak, "get_resource", return_value={"_id": "resource"})
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
                "audience": "global",
                "response_mode": "decision",
                'permission': 'resource#can_admin_dataset'
            }
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        kc_client: Keycloak = await Keycloak.create()

        with raises(UnauthorizedError) as exc:
            await kc_client.check_permissions("token", "can_admin_dataset", "resource", is_access_token=True)
        assert exc.value.description == 'User is not authorized'

    @mark.asyncio
    async def test_is_token_valid(self, keycloak_login_request_mock, respx_mock, mocker):
        mocker.patch.object(Keycloak, "check_permissions", return_value=True)
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_secret": "clientsecret",
                "client_id": "global",
                "grant_type": "refresh_token",
                "refresh_token": "token"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()

        assert await kc_client.is_token_valid("token", "can_admin_dataset", "resource")

    @mark.asyncio
    async def test_is_token_valid_without_permission_check(self, keycloak_login_request_mock, respx_mock, mocker):
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_secret": "clientsecret",
                "client_id": "global",
                "grant_type": "refresh_token",
                "refresh_token": "token"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        assert await kc_client.is_token_valid("token", "can_admin_dataset", "resource", with_permissions=False)

    @mark.asyncio
    async def test_is_token_valid_without_permission_check_fails(self, keycloak_login_request_mock, respx_mock, mocker):
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_secret": "clientsecret",
                "client_id": "global",
                "grant_type": "refresh_token",
                "refresh_token": "token"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        assert not await kc_client.is_token_valid("token", "can_admin_dataset", "resource", with_permissions=False)

    @mark.asyncio
    async def test_is_token_valid_fails(self, keycloak_login_request_mock, respx_mock, mocker):
        mocker.patch.object(Keycloak, "check_permissions", return_value=True)
        respx_mock.post(
            URLS["get_token"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                        "client_secret": "clientsecret",
                        "client_id": "global",
                        "grant_type": "refresh_token",
                        "refresh_token": "token"
                    }
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        assert not await kc_client.is_token_valid("token", "can_admin_dataset", "resource")

    @mark.asyncio
    async def test_is_token_valid_with_access(self, keycloak_login_request_mock, respx_mock, mocker):
        mocker.patch.object(Keycloak, "check_permissions", return_value=True)
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
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        assert await kc_client.is_token_valid("token", "can_admin_dataset", "resource", "access_token")
