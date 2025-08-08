from copy import deepcopy
import pytest
from unittest.mock import Mock

from app.helpers.exceptions import InvalidRequest
from app.models.container import Container
from tests.fixtures.azure_cr_fixtures import *


@pytest.fixture(scope='function')
def container_body(registry):
    return deepcopy({
        "name": "",
        "registry": registry.url,
        "tag": "1.2.3",
        "ml": True
    })


class ContainersMixin:
    def get_container_as_response(self, container):
        return {
            "dashboard": container.dashboard,
            "id": container.id,
            "name": container.name,
            "tag": container.tag,
            "ml": container.ml,
            "registry_id": container.registry_id
        }


class TestGetContainers(ContainersMixin):
    def test_docker_image_regex(
        self,
        container_body,
        cr_client,
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
            'app.models.task.Keycloak',
            return_value=Mock()
        )
        for im_format in valid_image_formats:
            container_body.update(im_format)
            Container.validate(container_body)

        for im_format in invalid_image_formats:
            container_body["name"] = im_format
            with pytest.raises(InvalidRequest):
                Container.validate(container_body)

    def test_get_all_images(
        self,
        client,
        container
    ):
        """
        Basic test for returning a correct response body
        on /GET /containers
        """
        resp = client.get(
            "/containers"
        )

        assert resp.json == [self.get_container_as_response(container)]

    def test_get_container_by_id(
        self,
        client,
        container,
        simple_admin_header
    ):
        """
        Basic test to make sure the response body has
        the expected format
        """
        resp = client.get(
            f"/containers/{container.id}",
            headers=simple_admin_header
        )

        assert resp.status_code == 200
        assert resp.json == self.get_container_as_response(container)

    def test_get_container_by_id_404(
        self,
        client,
        container,
        simple_admin_header
    ):
        """
        Basic test to make sure the response body has
        the expected format
        """
        resp = client.get(
            f"/containers/{container.id + 1}",
            headers=simple_admin_header
        )

        assert resp.status_code == 404
        assert resp.json["error"] == f'Container with id {container.id + 1} does not exist'

    def test_get_container_by_id_non_auth(
        self,
        client,
        container,
        simple_user_header
    ):
        """
        Basic test to make sure only admin users can
        use the endpoint
        """
        resp = client.get(
            f"/containers/{container.id}",
            headers=simple_user_header
        )

        assert resp.status_code == 403


class TestPostContainers(ContainersMixin):
    def test_add_new_container(
        self,
        client,
        registry,
        post_json_admin_header
    ):
        """
        Checks the POST body is what we expect
        """
        resp = client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url,
                "tag": "1.0.25"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 201
        assert Container.query.filter_by(
            name="testimage", tag="1.0.25"
        ).one_or_none() is not None

    def test_add_duplicate_container(
        self,
        client,
        registry,
        container,
        post_json_admin_header
    ):
        """
        Checks the POST request returns a 409 with a duplicate
        container entry
        """
        data = self.get_container_as_response(container)
        data["registry"] = registry.url
        resp = client.post(
            "/containers",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 409
        assert resp.json["error"] == f'Image {container.name}:{container.tag} already exists in registry {registry.url}'

    def test_add_new_container_missing_field(
        self,
        client,
        registry,
        post_json_admin_header
    ):
        """
        Checks the POST body is processed and returns
        an error if a required field is missing
        """
        resp = client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == 'Field "tag" missing'

    def test_add_new_container_invalid_registry(
        self,
        client,
        post_json_admin_header
    ):
        """
        Checks the POST request fails if the registry needed
        is not on record
        """
        resp = client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": "notreal",
                "tag": "0.0.1"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 500
        assert resp.json["error"] == 'Registry notreal could not be found'

    def test_container_name_invalid_format(
        self,
        client,
        registry,
        post_json_admin_header
    ):
        """
        If a tag is in an non supported format, return an error
        Most of the model validations are done in a previous test
        here we verifying the API returns the correct message
        """
        resp = client.post(
            "/containers",
            json={
                "name": "/testimage",
                "registry": registry.url,
                "tag": "0.1.1"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == '/testimage:0.1.1 does not have a tag. Please provide one in the format <image>:<tag>'


class TestPatchContainers:
    def test_patch_container(
        self,
        client,
        container,
        post_json_admin_header
    ):
        """
        Basic PATCH request test
        """
        resp = client.patch(
            f"/containers/{container.id}",
            json={"ml": True},
            headers=post_json_admin_header
        )
        assert resp.status_code == 204
        assert Container.query.filter_by(id=container.id).one_or_none().ml == True

    def test_patch_container_wrong_body(
        self,
        client,
        container,
        post_json_admin_header
    ):
        """
        Basic PATCH request test
        """
        resp = client.patch(
            f"/containers/{container.id}",
            json={"name": "new_name"},
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == "Either `ml` or `dashboard` field must be provided"

    def test_patch_container_non_existing_container(
        self,
        client,
        container,
        post_json_admin_header
    ):
        """
        Basic PATCH request test
        """
        resp = client.patch(
            f"/containers/{container.id + 1}",
            json={"ml": True},
            headers=post_json_admin_header
        )
        assert resp.status_code == 404
        assert resp.json["error"] == f"Container with id {container.id + 1} does not exist"

    def test_patch_container_non_json(
        self,
        client,
        container,
        login_admin
    ):
        """
        Basic PATCH request test
        """
        resp = client.patch(
            f"/containers/{container.id}",
            data={"ml": True},
            headers={"Authorization": f"Bearer {login_admin}"}
        )
        assert resp.status_code == 400
        assert resp.json["error"] == "Request body must be a valid json, or set the Content-Type to application/json"


class TestSync:
    def test_sync_200(
        self,
        client,
        post_json_admin_header,
        cr_client,
        tags_request,
        registry,
        expected_image_names,
        expected_tags_list
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry
        """
        resp = client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )
        expected_resp = [f"{registry.url}/{im}:{t}" for im in expected_image_names for t in expected_tags_list]
        assert resp.status_code == 201
        assert resp.json == expected_resp

    def test_sync_failure(
        self,
        client,
        post_json_admin_header,
        cr_name,
        registry
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry. Check that upon failure
        during the process no images are synched up
        """
        with responses.RequestsMock() as rsps:
            rsps.add_passthru(KEYCLOAK_URL)
            rsps.add(
                responses.GET,
                f"https://{cr_name}/oauth2/token?service={cr_name}&scope=registry:catalog:*",
                json={"error": "Credentials not valid"},
                status=401
            )
            resp = client.post(
                "/containers/sync",
                headers=post_json_admin_header
            )

        assert resp.status_code == 400
        assert resp.json["error"] == "Could not authenticate against the registry"

    def test_sync_no_action(
        self,
        client,
        post_json_admin_header,
        registry,
        container,
        azure_login_request,
        cr_name
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry. Check that no duplicate
        is added.
        """
        azure_login_request.add(
            responses.GET,
            f"https://{cr_name}/v2/{container.name}/tags/list",
            json={"tags": [container.tag]},
            status=200
        )
        azure_login_request.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{container.name}:metadata_read",
            json={"access_token": "12345asdf"},
            status=200
        )
        azure_login_request.add(
            responses.GET,
            f"https://{cr_name}/v2/_catalog",
            json={"repositories": [container.name]},
            status=200
        )
        resp = client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 201
        assert resp.json == []

    def test_sync_no_action_inactive_registry(
        self,
        client,
        post_json_admin_header,
        registry
    ):
        """
        Basic test that makes sure that if a registry is inactive
        nothing is done.
        """
        registry.active = False
        resp = client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 201
        assert resp.json == []
        assert Container.get_all() == []
