import base64
import json
import responses
from pytest import mark, raises

from tests.fixtures.dockerhub_cr_fixtures import *
from tests.fixtures.common_registry_fixtures import *
from app.helpers.exceptions import ContainerRegistryException


class TestDockerRegistry:
    """
    Different registry classes make different requests.
        This addressed the DockerHub case
    """
    login_url = "https://hub.docker.com/v2/users/login/"
    tags_url = "https://hub.docker.com/v2/namespaces/%s/repositories/%s/tags"

    @mark.asyncio
    async def test_cr_login_failed(
            self,
            registry_secret_mock,
            v1_registry_mock,
            registry,
            image_name,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the login fails.
        """
        auths = json.dumps({
            "auths": {registry.url: {
                "username": "test",
                "password": "test",
            }}
        })
        registry_secret_mock.data.update({
            ".dockerconfigjson": base64.b64encode(auths.encode()).decode()
        })
        respx_mock.get(
            self.login_url
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        with raises(ContainerRegistryException) as cre:
            DockerRegistry("registry", {"user": "", "token": ""}).login(image_name)
        assert cre.value.description == "Could not authenticate against the registry"

    @mark.asyncio
    async def test_cr_metadata_empty(
            self,
            cr_class,
            registry,
            container,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is an empty dictionary
        """
        respx_mock.get(
            "https://hub.docker.com/v2/users/login/"
        ).mock(
            return_value=httpx.Response(
                json={"token": "12345asdf"},
                status_code=200
            )
        )
        respx_mock.get(
            self.tags_url % (registry.url, container.name)
        ).mock(
            return_value=httpx.Response(
                json={"results": []},
                status_code=200
            )
        )
        assert {"name": container.name, "tag": [], "sha": []} == await cr_class.get_image_tags(container.name)

    @mark.asyncio
    async def test_cr_metadata_tag_not_in_api_response(
            self,
            cr_class,
            registry,
            container,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the
            tag is not in the list of the metadata info. Which is a `False`
        """
        respx_mock.get(
            self.login_url
        ).mock(
            return_value=httpx.Response(
                json={"token": "12345asdf"},
                status_code=200
            )
        )
        respx_mock.get(
            self.tags_url % (registry.url ,container.name)
        ).mock(
            return_value=httpx.Response(
                json={"results": [{"name": ["1.2.3", "dev"], "digest": "sha256:123ae123df"}]},
                status_code=200
            )
        )
        assert not await cr_class.has_image_tag_or_sha(container.name, "latest")

