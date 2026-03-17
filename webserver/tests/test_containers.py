from copy import deepcopy
from pytest import mark, raises
from pytest_asyncio import fixture

from sqlalchemy import select, update

from app.helpers.exceptions import InvalidRequest
from app.models.container import Container
from app.schemas.containers import ContainerCreate
from tests.fixtures.azure_cr_fixtures import *
from tests.base_test_class import BaseTest


@fixture(scope='function')
def container_body(registry):
    return deepcopy({
        "name": "",
        "registry": registry.url,
        "tag": "1.2.3",
        "ml": True
    })


class ContainersMixin(BaseTest):
    def get_container_as_response(self, container: Container):
        return {
            "dashboard": container.dashboard,
            "id": container.id,
            "name": container.name,
            "tag": container.tag,
            "sha": container.sha,
            "ml": container.ml,
            "registry_id": container.registry_id
        }


class TestGetContainers(ContainersMixin):
    @mark.asyncio
    async def test_docker_image_regex(
        self,
        container_body,
        registry_client,
        mocker,
        client
    ):
        """
        Tests that the docker image is in an expected format
            <namespace?/image>:<tag>
        """
        valid_image_formats = [
            {"name": "image", "tag": "3.21"},
            {"name": "image", "sha": "sha256:1234ab15ad48"},
            {"name": "namespace/image", "tag": "3.21"},
            {"name": "namespace/image", "tag": "3.21-alpha"}
        ]
        invalid_image_formats = [
            {"name": "not_valid/"},
            {"name": "/not-valid", "tag": ""},
            {"name": "/not-valid"},
            {"name": "image", "tag": ""},
            {"name": "namespace//image"},
            {"name": "not_valid/"}
        ]
        mocker.patch(
            'app.models.task.Keycloak.create',
            return_value=AsyncMock()
        )
        for im_format in valid_image_formats:
            container_body.update(im_format)
            ContainerCreate(**container_body)

        for im_format in invalid_image_formats:
            container_body["name"] = im_format
            with raises(InvalidRequest):
                ContainerCreate(**container_body)

    @mark.asyncio
    async def test_get_all_images(
        self,
        client,
        container,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test for returning a correct response body
        on /GET /containers
        """
        resp = await client.get("/containers", headers=post_json_admin_header)

        assert resp.json()["items"] == [self.get_container_as_response(container)]

    @mark.asyncio
    async def test_get_container_by_id(
        self,
        client,
        container,
        simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test to make sure the response body has
        the expected format
        """
        resp = await client.get(
            f"/containers/{container.id}",
            headers=simple_admin_header
        )

        assert resp.status_code == 200
        assert resp.json() == self.get_container_as_response(container)

    @mark.asyncio
    async def test_get_container_by_id_404(
        self,
        client,
        container,
        simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test to make sure the response body has
        the expected format
        """
        resp = await client.get(
            f"/containers/{container.id + 1}",
            headers=simple_admin_header
        )

        assert resp.status_code == 404
        assert resp.json()["error"] == f'Container with id {container.id + 1} does not exist'

    @mark.asyncio
    async def test_get_container_by_id_non_auth(
        self,
        client,
        container,
        simple_user_header,
        mock_kc_client_wrapper,
        base_kc_mock_args
    ):
        """
        Basic test to make sure only admin users can
        use the endpoint
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.get(
            f"/containers/{container.id}",
            headers=simple_user_header
        )

        assert resp.status_code == 403


class TestPostContainers(ContainersMixin):
    @mark.asyncio
    async def test_add_new_container(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST body is what we expect
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url,
                "tag": "1.0.25"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 201, resp.json()
        assert await self.run_query(select(Container).where(
            Container.name=="testimage", Container.tag=="1.0.25"
        ), "one_or_none") is not None

    @mark.asyncio
    async def test_add_new_container_by_sha(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST body is what we expect
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url,
                "sha": "sha256:123123123"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 201
        assert await self.run_query(select(Container).where(
            Container.name=="testimage", Container.sha=="sha256:123123123"
        ), "one_or_none") is not None

    @mark.asyncio
    async def test_add_duplicate_container(
        self,
        client,
        registry,
        container,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST request returns a 409 with a duplicate
        container entry
        """
        data = self.get_container_as_response(container)
        data["registry"] = registry.url
        resp = await client.post(
            "/containers",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == f'Image {container.name} with {container.tag} already exists in the registry'

    @mark.asyncio
    async def test_add_new_container_missing_field(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST body is processed and returns
        an error if a required field is missing
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == 'Make sure `tag` or `sha` are provided'

    @mark.asyncio
    async def test_add_new_container_invalid_registry(
        self,
        client,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST request fails if the registry needed
        is not on record
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": "notreal",
                "tag": "0.0.1"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == 'Registry notreal could not be found'

    @mark.asyncio
    async def test_container_name_invalid_format(
        self,
        client,
        registry,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        If a tag is in an non supported format, return an error
        Most of the model validations are done in a previous test
        here we verifying the API returns the correct message
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "/testimage",
                "registry": registry.url,
                "tag": "0.1.1"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == '/testimage:0.1.1 does not have a tag. Please provide one in the format <image>:<tag> or <image>@sha256..'


class TestPatchContainers(BaseTest):
    @mark.asyncio
    async def test_patch_container(
        self,
        client,
        container,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic PATCH request test
        """
        resp = await client.patch(
            f"/containers/{container.id}",
            json={"ml": True},
            headers=post_json_admin_header
        )
        assert resp.status_code == 201
        cont_db_obj: Container = await Container.get_by_id(self.db_session, container.id)
        assert cont_db_obj.ml == True

    @mark.asyncio
    async def test_patch_container_wrong_body(
        self,
        client,
        container,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic PATCH request test
        """
        resp = await client.patch(
            f"/containers/{container.id}",
            json={"name": "new_name"},
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "No valid changes detected"

    @mark.asyncio
    async def test_patch_container_non_existing_container(
        self,
        client,
        container,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic PATCH request test
        """
        resp = await client.patch(
            f"/containers/{container.id + 1}",
            json={"ml": True},
            headers=post_json_admin_header
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == f"Container with id {container.id + 1} does not exist"

    @mark.asyncio
    async def test_patch_container_non_json(
        self,
        client,
        container,
        simple_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic PATCH request test in invalid format
        """
        resp = await client.patch(
            f"/containers/{container.id}",
            data={"ml": True},
            headers=simple_admin_header
        )
        assert resp.status_code == 400
        assert 'Input should be a valid dictionary or object to extract fields from' == resp.json()["error"][0]["message"]


class TestSync(BaseTest):
    @mark.asyncio
    async def test_sync_200(
        self,
        client,
        post_json_admin_header,
        tags_request,
        registry,
        expected_image_names,
        expected_tags_list,
        expected_digest_list,
        mock_kc_client_wrapper
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry
        """
        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )
        expected_resp = [
            'acr.azurecr.io/testimage:1.2.3',
            'acr.azurecr.io/testimage:dev',
            'acr.azurecr.io/testimage:latest',
            'acr.azurecr.io/example:1.2.3',
            'acr.azurecr.io/example:dev',
            # 'acr.azurecr.io/example:latest', This is already present and not synched
            'acr.azurecr.io/testimage@sha256:c1e51a68c68a448a',
            'acr.azurecr.io/example@sha256:c1e51a68c68a448a'
        ]
        assert resp.status_code == 201
        assert sorted(resp.json()["images"]) == sorted(expected_resp)

    @mark.asyncio
    async def test_sync_failure(
        self,
        client,
        post_json_admin_header,
        cr_name,
        respx_mock,
        registry,
        mock_kc_client_wrapper
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry. Check that upon failure
        during the process no images are synched up
        """
        respx_mock.get(
            f"https://{cr_name}/oauth2/token",
            params={
                "service": cr_name,
                "scope": "registry:catalog:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"error": "Credentials not valid"},
                status_code=401
            )
        )
        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "Could not authenticate against the registry"

    @mark.asyncio
    async def test_sync_no_action(
        self,
        client,
        post_json_admin_header,
        registry,
        container,
        container_with_sha,
        azure_login_request,
        cr_name,
        mock_kc_client_wrapper,
        respx_mock
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry. Check that no duplicate
        is added.
        """
        respx_mock.get(
            f"https://{cr_name}/oauth2/token",
            params={
                "service": cr_name,
                "scope": f"repository:{container.name}:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "12345asdf"},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/{container.name}/tags/list"
        ).mock(
            return_value=httpx.Response(
                json={"tags": [container.tag]},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/{container.name}/manifests/{container.tag}",
        ).mock(
            return_value=httpx.Response(
                json={"config": {"digest": container_with_sha.sha}},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/_catalog"
        ).mock(
            return_value=httpx.Response(
                json={"repositories": [container.name]},
                status_code=200
            )
        )
        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 201, resp.json()
        assert resp.json()["images"] == []

    @mark.asyncio
    async def test_sync_no_action_inactive_registry(
        self,
        client,
        post_json_admin_header,
        registry,
        mock_kc_client_wrapper
    ):
        """
        Basic test that makes sure that if a registry is inactive
        nothing is done.
        """
        await self.db_session.execute(update(Registry).where(Registry.id == registry.id).values({"active": False}))

        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 201
        assert resp.json()["images"] == []
        assert await self.run_query(select(Container)) == []
