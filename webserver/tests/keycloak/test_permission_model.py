import httpx
from pytest import mark, raises
import responses
from responses import matchers
from datetime import datetime as dt, timedelta as td
from app.helpers.exceptions import KeycloakError
from app.helpers.keycloak import URLS, Keycloak
from tests.keycloak.test_keycloak_helper import TestKeycloakMixin


class TestKeycloakPolicies(TestKeycloakMixin):
    """
    """
    payload = {
        "name": "1-dataset Admin Policy",
        "description": f"List of users allowed to administrate the dataset dataset",
        "logic": "POSITIVE",
        "users": ["user_id"]
    }

    @mark.asyncio
    async def test_get_policy_fails(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that exceptions are raised with an unsuccessful response
        """
        respx_mock.get(
            URLS["policies"] % "clientid",
            params={
                "permission": False,
                "name": self.payload["name"]
            }
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        with raises(KeycloakError) as exc:
            await kc_client.get_policy(self.payload["name"])
        assert exc.value.description == "Error when fetching the policies from Keycloak"

    @mark.asyncio
    async def test_create_policy(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that no exceptions are raised with a successful response
        """
        respx_mock.post(
            (URLS["policies"] % "clientid") + "/user",
        ).mock(
            return_value=httpx.Response(
                json={"id": "policy_id"},
                status_code=201
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_policy(self.payload, "/user")

    @mark.asyncio
    async def test_create_policy_409_accepted(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that no exceptions are raised with a 409 response. It also
        checks that the existing policy is fetched
        """
        respx_mock.post(
            (URLS["policies"] % "clientid") + "/user",
        ).mock(
            return_value=httpx.Response(
                status_code=409
            )
        )
        respx_mock.get(
            URLS["policies"] % "clientid",
            params={
                "permission": False,
                "name": self.payload["name"]
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "policy_id"}],
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_policy(self.payload, "/user")

    @mark.asyncio
    async def test_create_policy_failed_request(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that exceptions are raised with an unsuccessful response
        """
        respx_mock.post(
            (URLS["policies"] % "clientid") + "/user",
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        with raises(KeycloakError) as exc:
            await kc_client.create_policy(self.payload, "/user")
        assert exc.value.description == "Failed to create a project's policy"


class TestKeycloakScopes(TestKeycloakMixin):
    """
    """
    @mark.asyncio
    async def test_get_scope_fails(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that exceptions are raised with an unsuccessful response
        """
        respx_mock.get(
            URLS["scopes"] % "clientid",
            params={
                "permission": False,
                "name": "can_admin_dataset"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        with raises(KeycloakError) as exc:
            await kc_client.get_scope("can_admin_dataset")
        assert exc.value.description == "Error when fetching the scopes from Keycloak"

    @mark.asyncio
    async def test_create_scope(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that no exceptions are raised with a successful response
        """
        respx_mock.post(
            URLS["scopes"] % "clientid"
        ).mock(
            return_value=httpx.Response(
                json={"id": "permission_id"},
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_scope("can_admin_dataset")

    @mark.asyncio
    async def test_create_scope_409_accepted(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that no exceptions are raised with a 409 response
        """
        respx_mock.post(
            URLS["scopes"] % "clientid"
        ).mock(
            return_value=httpx.Response(
                status_code=409
            )
        )
        respx_mock.get(
            URLS["scopes"] % "clientid"
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "scope_id"}],
                status_code=200
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_scope("can_admin_dataset")

    @mark.asyncio
    async def test_create_scope_failed_request(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that exceptions are raised with an unsuccessful response
        """
        respx_mock.post(
            URLS["scopes"] % "clientid"
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        with raises(KeycloakError) as exc:
            await kc_client.create_scope("can_admin_dataset")
        assert exc.value.description == "Failed to create a project's scope"


class TestKeycloakPermissions(TestKeycloakMixin):
    """
    """
    payload = {
        "name": "1-dataset Admin Permission",
        "description": "List of policies that will allow certain users or roles to administrate the dataset",
        "type": "resource",
        "logic": "POSITIVE",
        "decisionStrategy": "AFFIRMATIVE",
        "policies": ["admin_policy", "sys_policy", "policy"],
        "resources": ["resource_ds"],
        "scopes": ["scope_id"]
    }

    @mark.asyncio
    async def test_create_permission(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that no exceptions are raised with a successful response
        """
        respx_mock.post(
            URLS["permission"] % "clientid",
        ).mock(
            return_value=httpx.Response(
                json={"id": "permission_id"},
                status_code=201
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_permission(self.payload)

    @mark.asyncio
    async def test_create_permission_409_accepted(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that no exceptions are raised with a 409 response
        """
        respx_mock.post(
            URLS["permission"] % "clientid",
        ).mock(
            return_value=httpx.Response(
                json={"id": "permission_id"},
                status_code=409
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_permission(self.payload)

    @mark.asyncio
    async def test_create_permission_failed_request(self, keycloak_login_request_mock, respx_mock):
        """
        Simply tests that exceptions are raised with an unsuccessful response
        """
        respx_mock.post(
            URLS["permission"] % "clientid",
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        with raises(KeycloakError) as exc:
            await kc_client.create_permission(self.payload)
        assert exc.value.description == "Failed to create a project's permission"


class TestKeycloakTimePolicy(TestKeycloakMixin):
    """
    Time policies are treated differently than a normal policy.
        - policy doesn't exist => create a new one
        - policy already exists => fetch it and update the time constraints
    """
    payload = {
        "name": "user_id Date access policy",
        "description": "Date range to allow the user to access a dataset within this project",
        "logic": "POSITIVE",
        "notBefore": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "notOnOrAfter": (dt.now() + td(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    }

    @mark.asyncio
    async def test_create_or_update_time_policy(self, keycloak_login_request_mock, respx_mock):
        """
        - policy doesn't exist => create a new one
        """
        respx_mock.post(
            (URLS["policies"] % "clientid") + "/time",
        ).mock(
            return_value=httpx.Response(
                json={"id": "policy_id"},
                status_code=201
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_or_update_time_policy(self.payload, "/time")

    @mark.asyncio
    async def test_create_or_update_time_policy_exists(self, keycloak_login_request_mock, respx_mock):
        """
        - policy already exists => fetch it and update the time constraints
        """
        respx_mock.post(
            (URLS["policies"] % "clientid") + "/time",
        ).mock(
            return_value=httpx.Response(
                status_code=409
            )
        )
        respx_mock.get(
            URLS["policies"] % "clientid",
            params={
                "permission": False,
                "name": self.payload["name"]
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "policy_id", "config": {"noa": "01/01/2025", "nbf": "02-01-2025"}}],
                status_code=200
            )
        )
        respx_mock.put(
            (URLS["policies"] % "clientid") + "/policy_id"
        ).mock(
            return_value=httpx.Response(
                status_code=201
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        await kc_client.create_or_update_time_policy(self.payload, "/time")

    @mark.asyncio
    async def test_create_or_update_time_policy_fails(self, keycloak_login_request_mock, respx_mock):
        """
        policy patching fails
        """
        respx_mock.post(
            (URLS["policies"] % "clientid") + "/time",
        ).mock(
            return_value=httpx.Response(
                status_code=409
            )
        )
        respx_mock.get(
            URLS["policies"] % "clientid",
            params={
                "permission": False,
                "name": self.payload["name"]
            }
        ).mock(
            return_value=httpx.Response(
                json=[{"id": "policy_id", "config": {"noa": "01/01/2025", "nbf": "02-01-2025"}}],
                status_code=200
            )
        )
        respx_mock.put(
            (URLS["policies"] % "clientid") + "/policy_id"
        ).mock(
            return_value=httpx.Response(
                status_code=400
            )
        )
        kc_client: Keycloak = await Keycloak.create()
        with raises(KeycloakError) as exc:
            await kc_client.create_or_update_time_policy(self.payload, "/time")
        assert exc.value.description == "Failed to create a project's policy"
