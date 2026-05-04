from copy import deepcopy
import pytest
from http import HTTPStatus
from unittest.mock import Mock
from unittest import mock

from app.helpers.exceptions import InvalidRequest, ContainerRegistryException
from app.helpers.base_model import db
from app.models.container import Container
from tests.fixtures.azure_cr_fixtures import *

@pytest.fixture(scope='function')
def container_body(registry):
    return deepcopy({
        "name": "",
        "registry": registry.url,
        "tag": "1.2.3"
    })

class ContainersMixin:
    def get_container_as_response(self, container: Container):
        return {
            "id": container.id,
            "name": container.name,
            "tag": container.tag,
            "sha": container.sha,
            "registry_id": container.registry_id
        }

@pytest.mark.parametrize("enable_image_whitelist", [True, False])
class TestContainers(ContainersMixin):

    @pytest.fixture(autouse=True)
    def setup_validation(self, mocker, enable_image_whitelist):
        """
        Mocks the ENABLE_IMAGE_WHITELIST constant in both the API and the helper
        to ensure consistency across both branches of the test.
        """
        mocker.patch("app.containers_api.ENABLE_IMAGE_WHITELIST", enable_image_whitelist)
        mocker.patch("app.helpers.const.ENABLE_IMAGE_WHITELIST", enable_image_whitelist)

    def test_docker_image_regex(
        self,
        container_body,
        mocker
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

    def test_get_all_containers(self, client, container, enable_image_whitelist):
        """
        Basic test for returning a correct response body
        on /GET /containers
        """
        resp = client.get("/containers")
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.OK
        assert any(item["id"] == container.id for item in resp.json["items"])

    def test_get_image_by_id(self, client, container, enable_image_whitelist, post_json_admin_header):
        """
        Basic test to make sure the response body has
        the expected format
        """
        resp = client.get(f"/containers/{container.id}", headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.OK
        assert resp.json["id"] == container.id

    def test_get_image_by_id_404(self, client, container, enable_image_whitelist, post_json_admin_header):
        """
        Basic test to make sure the response body has
        the expected format
        """
        resp = client.get(f"/containers/{container.id + 1}", headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.NOT_FOUND

    def test_get_image_by_id_non_auth(self, client, container, enable_image_whitelist, simple_user_header, mock_kc_client):
        """
        Basic test to make sure only admin users can
        use the endpoint
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        resp = client.get(f"/containers/{container.id}", headers=simple_user_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN # Gate hook runs first
            return
        assert resp.status_code == HTTPStatus.FORBIDDEN # auth wrapper returns 403

    def test_delete_image(self, client, container, enable_image_whitelist, post_json_admin_header):
        """
        Basic test for DELETE /containers/<image_id>
        """
        resp = client.delete(f"/containers/{container.id}", headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.OK
        assert db.session.get(Container, container.id) is None

    def test_delete_image_404(self, client, container, enable_image_whitelist, post_json_admin_header):
        """
        Test DELETE /containers/<image_id> with non-existent id
        """
        resp = client.delete(f"/containers/{container.id + 1}", headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.NOT_FOUND

    def test_delete_image_non_auth(self, client, container, enable_image_whitelist, simple_user_header, mock_kc_client):
        """
        Test DELETE /containers/<image_id> with non-admin user
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        resp = client.delete(f"/containers/{container.id}", headers=simple_user_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.FORBIDDEN

    def test_add_image(self, client, registry, enable_image_whitelist, post_json_admin_header):
        """
        Checks the POST body is what we expect
        """
        image_data = {"name": "new-image", "registry": registry.url, "tag": "latest"}
        resp = client.post("/containers", json=image_data, headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.CREATED
        assert Container.query.filter_by(name="new-image", tag="latest").one_or_none() is not None

    def test_add_new_container_by_sha(self, client, registry, enable_image_whitelist, post_json_admin_header):
        """
        Checks the POST body is what we expect
        """
        sha = "sha256:123123123123"
        image_data = {"name": "sha-image", "registry": registry.url, "sha": sha}
        resp = client.post("/containers", json=image_data, headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.CREATED
        assert Container.query.filter_by(name="sha-image", sha=sha).one_or_none() is not None

    def test_add_existing_image(self, client, container, enable_image_whitelist, post_json_admin_header):
        """
        Checks the POST request returns a 409 with a duplicate
        container entry
        """
        image_data = {"name": container.name, "registry": container.registry.url, "tag": container.tag}
        resp = client.post("/containers", json=image_data, headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.CONFLICT

    def test_add_new_container_missing_field(self, client, registry, enable_image_whitelist, post_json_admin_header):
        """
        Checks the POST body is processed and returns
        an error if a required field is missing
        """
        image_data = {"name": "testimage", "registry": registry.url}
        resp = client.post("/containers", json=image_data, headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert resp.json["error"] == 'Make sure `tag` or `sha` are provided'

    def test_add_new_container_invalid_registry(self, client, enable_image_whitelist, post_json_admin_header):
        """
        Checks the POST request fails if the registry needed
        is not on record
        """
        image_data = {"name": "testimage", "registry": "notreal", "tag": "v1"}
        resp = client.post("/containers", json=image_data, headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return
        assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'Registry notreal could not be found' in resp.json["error"]

    def test_container_name_invalid_format(self, client, registry, enable_image_whitelist, post_json_admin_header):
        """
        If a tag is in an non supported format, return an error
        Most of the model validations are done in a previous test
        here we verifying the API returns the correct message
        """
        if not enable_image_whitelist:
            # Skip loop as it just returns 403 anyway
            resp = client.post("/containers", json={}, headers=post_json_admin_header)
            assert resp.status_code == HTTPStatus.FORBIDDEN
            return

        for inv_name in ["/testimage", "a/", "i"]:
            resp = client.post(
                "/containers",
                json={
                    "name": inv_name,
                    "registry": registry.url,
                    "tag": "0.1.1"
                },
                headers=post_json_admin_header
            )
            assert resp.status_code == HTTPStatus.BAD_REQUEST
            assert 'is malformed' in resp.json["error"]

class TestContainerModelValidation:
    def test_container_validate_missing_registry(self, client):
        """Test Container.validate when registry doesn't exist"""
        with pytest.raises(ContainerRegistryException) as exc:
            Container.validate({"name": "test", "registry": "non-existent.io", "tag": "latest"})
        assert "Registry non-existent.io could not be found" in str(exc.value)

    def test_whitelist_image_only_matches_any_version(self, registry):
        """Whitelisting an image without tag or SHA should allow any version of that image"""
        img = Container(name="img1", registry=registry, tag=None, sha=None)
        img.add()
        assert Container.validate_image_whitelisted(f"{registry.url}/img1:any-tag") is True
        assert Container.validate_image_whitelisted(f"{registry.url}/img1@sha256:{"a"*64}") is True

    def test_whitelist_image_and_tag_matches_specific_tag(self, registry):
        """Whitelisting an image and tag should allow only that tag"""
        img = Container(name="img2", registry=registry, tag="v1", sha=None)
        img.add()
        assert Container.validate_image_whitelisted(f"{registry.url}/img2:v1") is True
        assert Container.validate_image_whitelisted(f"{registry.url}/img2:v2") is False

    def test_whitelist_image_tag_and_sha_matches_direct_sha_request(self, registry):
        """Whitelisting image, tag, and SHA should allow requests matching both tag and SHA"""
        s1 = "sha256:" + "1" * 64
        img = Container(name="img3", registry=registry, tag="v1", sha=s1)
        img.add()
        
        # Mock remote resolution to avoid actual registry calls during tests
        with mock.patch("app.models.registry.Registry.get_registry_class") as mock_reg_class:
            mock_client = mock_reg_class.return_value
            mock_client.has_image_tag_or_sha.return_value = True

            # Full match: Tag + SHA
            assert Container.validate_image_whitelisted(f"{registry.url}/img3:v1@{s1}") is True
            # Tag matches, SHA doesn't
            assert Container.validate_image_whitelisted(f"{registry.url}/img3:v1@sha256:different") is False
            # SHA matches, Tag doesn't (whitelisting is tag-restricted)
            assert Container.validate_image_whitelisted(f"{registry.url}/img3:v2@{s1}") is False
            # Only SHA provided (whitelisting is tag-restricted)
            assert Container.validate_image_whitelisted(f"{registry.url}/img3@{s1}") is False

    def test_whitelist_image_tag_and_sha_matches_remote_resolution(self, registry):
        """Whitelisting image, tag, and SHA should allow tag-only requests if remote SHA matches"""
        s1 = "sha256:" + "1" * 64
        img = Container(name="img3", registry=registry, tag="v1", sha=s1)
        img.add()
        with mock.patch("app.models.registry.Registry.get_registry_class") as mock_reg_class:
            mock_client = mock_reg_class.return_value
            # Tag matches, remote SHA matches
            mock_client.get_tag_sha.return_value = s1
            assert Container.validate_image_whitelisted(f"{registry.url}/img3:v1") is True
            # Tag matches, remote SHA doesn't match
            mock_client.get_tag_sha.return_value = "sha256:different"
            assert Container.validate_image_whitelisted(f"{registry.url}/img3:v1") is False

    def test_whitelist_image_and_sha_matches_direct_sha_request(self, registry):
        """Whitelisting image and SHA (without tag) should allow any tag matching that SHA"""
        s4 = "sha256:" + "4" * 64
        img = Container(name="img4", registry=registry, tag=None, sha=s4)
        img.add()
        # Match by SHA directly
        assert Container.validate_image_whitelisted(f"{registry.url}/img4@{s4}") is True
        # Match by Tag + SHA
        assert Container.validate_image_whitelisted(f"{registry.url}/img4:any-tag@{s4}") is True

    def test_whitelist_image_and_sha_matches_remote_resolution(self, registry):
        """Whitelisting image and SHA (without tag) should allow tag-only requests if remote SHA matches"""
        s4 = "sha256:" + "4" * 64
        img = Container(name="img4", registry=registry, tag=None, sha=s4)
        img.add()
        with mock.patch("app.models.registry.Registry.get_registry_class") as mock_reg_class:
            mock_client = mock_reg_class.return_value
            # Remote SHA matches
            mock_client.get_tag_sha.return_value = s4
            assert Container.validate_image_whitelisted(f"{registry.url}/img4:any-tag") is True
            # Remote SHA doesn't match
            mock_client.get_tag_sha.return_value = "sha256:different"
            assert Container.validate_image_whitelisted(f"{registry.url}/img4:any-tag") is False


    def test_whitelist_ignores_remote_existence_check(self, registry):
        """Whitelisting should succeed if the image is in the DB, regardless of remote existence"""
        img = Container(name="img-exists", registry=registry, tag="v1", sha=None)
        img.add()
        
        with mock.patch("app.models.registry.Registry.get_registry_class") as mock_reg_class:
            mock_client = mock_reg_class.return_value
            # Whitelisted in DB, but doesn't exist remotely
            mock_client.get_tag_sha.return_value = None
            assert Container.validate_image_whitelisted(f"{registry.url}/img-exists:v1") is True
            
            # Whitelisted by SHA, but doesn't exist remotely
            s1 = "sha256:" + "s" * 64
            img_sha = Container(name="img-sha", registry=registry, tag=None, sha=s1)
            img_sha.add()
            mock_client.has_image_tag_or_sha.return_value = False
            assert Container.validate_image_whitelisted(f"{registry.url}/img-sha@{s1}") is True
