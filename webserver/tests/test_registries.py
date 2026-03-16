from pytest import mark
import base64
import json
from kubernetes_asyncio.client import ApiException
from sqlalchemy import func, select

from app.helpers.const import TASK_NAMESPACE
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.common_registry_fixtures import *
from tests.base_test_class import BaseTest


class TestGetRegistriesApi(BaseTest):
    @mark.asyncio
    async def test_list_200(
        self,
        registry,
        client,
        simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test for the GET /registries endpoint
        ensuring the expected response body
        """
        resp = await client.get(
            "/registries",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == [{
            'id': registry.id,
            'needs_auth': registry.needs_auth,
            'active': registry.active,
            'url': registry.url
        }]

    @mark.asyncio
    async def test_list_non_admin_403(
        self,
        registry,
        client,
        simple_user_header,
        v1_registry_mock,
        mock_kc_client_wrapper,
        base_kc_mock_args
    ):
        """
        Basic test for the GET /registries endpoint
        ensuring only admins can get information
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.get(
            "/registries",
            headers=simple_user_header
        )
        assert resp.status_code == 403

    @mark.asyncio
    async def test_list_no_auth_401(
        self,
        registry,
        client,
        mock_kc_client_wrapper
    ):
        """
        Basic test for the GET /registries endpoint
        ensuring only admins can get information
        """
        resp = await client.get("/registries")
        assert resp.status_code == 401

    @mark.asyncio
    async def test_get_registry_by_id(
        self,
        registry,
        client,
        simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test to check that the registry
        output is correct with appropriate permissions
        """
        resp = await client.get(
            f"registries/{registry.id}",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "id": registry.id,
            "needs_auth": registry.needs_auth,
            'active': registry.active,
            "url": registry.url
        }


    @mark.asyncio
    async def test_get_registry_by_id_not_found(
        self,
        registry,
        client,
        simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test that a 404 is return with an
        appropriate message
        """
        resp = await client.get(
            f"registries/{registry.id + 1}",
            headers=simple_admin_header
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == f"Registry with id {registry.id + 1} does not exist"

    @mark.asyncio
    async def test_get_registry_by_id_non_admin_403(
        self,
        registry,
        client,
        simple_user_header,
        mock_kc_client_wrapper,
        base_kc_mock_args
    ):
        """
        Basic test to ensure only admins can browse
        by registry id
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.get(
            f"registries/{registry.id}",
            headers=simple_user_header
        )
        assert resp.status_code == 403


class TestPostRegistriesApi(BaseTest):
    @mark.asyncio
    async def test_create_registry_201(
        self,
        client,
        post_json_admin_header,
        v1_registry_mock,
        dockerconfigjson_mock,
        v1_ds_mock,
        respx_mock,
        mock_kc_client_wrapper
    ):
        """
        Basic POST request
        """
        v1_registry_mock.api_client.read_namespaced_secret.return_value = Mock(data=dockerconfigjson_mock)
        new_registry = "shiny.azurecr.io"

        respx_mock.get(
            f"https://{new_registry}/oauth2/token",
            params={
                "service": new_registry,
                "scope": "registry:catalog:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "12jio12buds89"},
                status_code=200
            )
        )
        resp = await client.post(
            "/registries",
            json={
                "url": new_registry,
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 201

    @mark.asyncio
    async def test_create_registry_incorrect_creds(
        self,
        client,
        post_json_admin_header,
        respx_mock,
        mock_kc_client_wrapper
    ):
        """
        Basic POST request with incorrect credentials
        """
        new_registry = "shiny.azurecr.io"
        respx_mock.get(
            f"https://{new_registry}/oauth2/token",
            params={
                "service": new_registry,
                "scope": "registry:catalog:*"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        resp = await client.post(
            "/registries",
            json={
                "url": new_registry,
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "Could not authenticate against the registry"

    @mark.asyncio
    async def test_create_registry_k8s_error(
        self,
        client,
        v1_registry_mock,
        mock_args_k8s,
        post_json_admin_header,
        respx_mock,
        mock_kc_client_wrapper
    ):
        """
        Basic POST request when the docker secret does not exist, so it get correctly
        created
        """
        new_registry = "shiny.azurecr.io"
        mock_args_k8s.api_client.read_namespaced_secret.side_effect = [
            ApiException(status=500, reason="Failed")
        ]

        respx_mock.get(
            f"https://{new_registry}/oauth2/token",
            params={
                "service": new_registry,
                "scope": "registry:catalog:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "12jio12buds89"},
                status_code=200
            )
        )
        resp = await client.post(
            "/registries",
            json={
                "url": new_registry,
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert await self.run_query(select(Registry).where(Registry.url == new_registry), "one_or_none") is None

    @mark.asyncio
    async def test_create_registry_missing_secret(
        self,
        client,
        v1_registry_mock,
        mock_args_k8s,
        post_json_admin_header,
        respx_mock,
        mock_kc_client_wrapper
    ):
        """
        Basic POST request when the docker secret does not exist, so it get correctly
        created
        """
        new_registry = "shiny.azurecr.io"
        mock_args_k8s.api_client.read_namespaced_secret.side_effect = [
            ApiException(status=404, reason="Not Found"),
            Mock(data={
                ".dockerconfigjson": base64.b64encode("{\"auths\": {}}".encode()).decode()
            })
        ]
        respx_mock.get(
            f"https://{new_registry}/oauth2/token",
            params={
                "service": new_registry,
                "scope": "registry:catalog:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "12jio12buds89"},
                status_code=200
            )
        )
        resp = await client.post(
            "/registries",
            json={
                "url": new_registry,
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 201

    @mark.asyncio
    async def test_create_missing_field(
        self,
        client,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks that required fields missing return
        an error message
        """
        resp = await client.post(
            "/registries",
            json={
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"][0] == {'field': ['body', 'url'], 'message': 'Field required', 'type': 'missing'}

    @mark.asyncio
    async def test_create_duplicate(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks that creating a registry with the same
        url as an existing one, fails
        """
        resp = await client.post(
            "/registries",
            json={
                "url": registry.url,
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == f"Registry {registry.url} already exist"
        assert await self.run_query(select(func.count(Registry.id)).where(Registry.url==registry.url), "one") == 1


class TestDeleteRegistries(BaseTest):
    @mark.asyncio
    async def test_delete_registry(
            self,
            client,
            registry,
            v1_registry_mock,
            mock_args_k8s,
            simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Simple test to check a successful deletion from the
        DB and its k8s secrets
        """
        secret_name = registry.slugify_name()
        response = await client.delete(
            f"/registries/{registry.id}",
            headers=simple_admin_header
        )
        assert response.status_code == 204
        mock_args_k8s.api_client.delete_namespaced_secret.assert_called_with(
            **{"name": secret_name, "namespace": TASK_NAMESPACE}
        )

    @mark.asyncio
    async def test_delete_registry_not_found(
            self,
            client,
            registry,
            v1_registry_mock,
            simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Return a 404 response if a registry cannot be found
        """
        response = await client.delete(
            f"/registries/{registry.id + 1}",
            headers=simple_admin_header
        )
        assert response.status_code == 404

    @mark.asyncio
    async def test_delete_registry_k8s_error(
            self,
            client,
            registry,
            v1_registry_mock,
            mock_args_k8s,
            simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Return a 500 stauts code when a k8s exception is raised
            but the db record is still deleted. This is an intentional
            behaviour as the sync and container check are based
            on the db entry. Secrets can stay if k8s fails.
        """
        mock_args_k8s.api_client.delete_namespaced_secret.side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data="Invalid value in data")
        )
        reg_id = registry.id
        response = await client.delete(
            f"/registries/{reg_id}",
            headers=simple_admin_header
        )
        assert response.status_code == 500
        assert await Registry.get_by_id(self.db_session, reg_id, raise_if_not_found=False) is not None

    @mark.asyncio
    async def test_delete_cascade_containers(
            self,
            client,
            registry,
            v1_registry_mock,
            simple_admin_header,
            db_session,
        mock_kc_client_wrapper
    ):
        """
        Tests that by simply deleting a registry all of its
        containers are deleted as well
        """
        reg_id = registry.id
        await Container(
            registry=registry,
            name="newimage",
            tag="1.0.0"
        ).add(db_session)
        await Container(
            registry=registry,
            name="newimage",
            tag="1.3.0"
        ).add(db_session)

        response = await client.delete(
            f"/registries/{reg_id}",
            headers=simple_admin_header
        )
        assert response.status_code == 204
        assert await Registry.get_by_id(self.db_session, reg_id, raise_if_not_found=False) is None
        assert await self.run_query(select(func.count(Container.id)).where(
            Container.name=="newimage", Container.registry_id==reg_id
            ), "one") == 0


class TestPatchRegistriesApi(BaseTest):
    @mark.asyncio
    async def test_patch_registry(
        self,
        client,
        registry,
        post_json_admin_header,
        v1_registry_mock,
        mock_args_k8s,
        mock_kc_client_wrapper
    ):
        """
        Simple PATCH request test to check the db record is updated
        """
        data = {
            "active": not registry.active
        }
        resp = await client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 204
        assert await self.run_query(
            select(func.count(Registry.id)).where(Registry.id==registry.id, Registry.active == data["active"])
        , "one") == 1
        # it patches the regcreds-like secret at registry creation
        mock_args_k8s.api_client.patch_namespaced_secret.call_count == 1

    @mark.asyncio
    async def test_patch_registry_credentials(
        self,
        client,
        registry,
        post_json_admin_header,
        v1_registry_mock,
        mock_args_k8s,
        dockerconfigjson_mock,
        mock_kc_client_wrapper
    ):
        """
        Simple PATCH request test to check the registry credentials
        are updated
        """
        data = {
            "password": "new password token",
            "username": "shiny"
        }
        # mock_args_k8s.api_client.read_namespaced_secret.return_value.data = dockerconfigjson_mock

        resp = await client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 204
        mock_args_k8s.api_client.patch_namespaced_secret.assert_called()

        # Only look after the first invocation as the first comes from the registry creation
        reg_secret = mock_args_k8s.api_client.patch_namespaced_secret.call_args_list[0][1]

        dockerconfig = base64.b64decode(reg_secret['body'].data['.dockerconfigjson']).decode()
        assert json.loads(dockerconfig)["auths"][registry.url]["password"] == data["password"]
        assert json.loads(dockerconfig)["auths"][registry.url]["username"] == data["username"]
        assert reg_secret["name"] == "acr-azurecr-io"

    @mark.asyncio
    async def test_patch_registry_empty_body(
        self,
        client,
        registry,
        post_json_admin_header,
        v1_registry_mock,
        mock_args_k8s,
        mock_kc_client_wrapper
    ):
        """
        Simple PATCH request test to check the registry credentials
        are updated
        """
        data = {}
        resp = await client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "No valid changes detected"
        # it patches the regcreds-like secret at registry creation
        mock_args_k8s.api_client.patch_namespaced_secret.call_count == 1

    @mark.asyncio
    async def test_patch_registry_non_existent(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Simple PATCH request test to ensure that trying to patch
        an non existing registry returns an error
        """
        data = {
            "active": not registry.active
        }
        resp = await client.patch(
            f"registries/{registry.id + 1}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == f"Registry with id {registry.id + 1} does not exist"

    @mark.asyncio
    async def test_patch_registry_url_change_not_allowed(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Simple PATCH request test to ensure that trying to change a url
        is not allowed. New url should be a new registry
        """
        data = {
            "host": "fancy.acr.io"
        }
        resp = await client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "No valid changes detected"

    @mark.asyncio
    async def test_patch_registry_k8s_fail(
        self,
        client,
        registry,
        post_json_admin_header,
        v1_registry_mock,
        mock_args_k8s,
        mock_kc_client_wrapper
    ):
        """
        Simple PATCH request test to check the db record is updated
        """
        data = {
            "password": "pass"
        }
        mock_args_k8s.api_client.patch_namespaced_secret.side_effect = ApiException(
            http_resp=Mock(status=500, body="details", reason="Failed")
        )

        resp = await client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "Could not update credentials"
