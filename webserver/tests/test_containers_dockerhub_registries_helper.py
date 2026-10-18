import base64
import json
import responses
from tests.fixtures.dockerhub_cr_fixtures import *
from app.helpers.exceptions import ContainerRegistryException


class TestDockerRegistry:
    """
    Different registry classes make different requests.
        This addressed the DockerHub case
    """
    login_url = "https://hub.docker.com/v2/users/login/"
    tags_url = "https://hub.docker.com/v2/namespaces/%s/repositories/%s/tags"

    def test_cr_login_failed(
            self,
            k8s_client,
            reg_k8s_client,
            registry,
            image_name
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
        reg_k8s_client["read_namespaced_secret_mock"].return_value.data.update({
            ".dockerconfigjson": base64.b64encode(auths.encode()).decode()
        })
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                self.login_url,
                status=401
            )
            with pytest.raises(ContainerRegistryException) as cre:
                DockerRegistry("registry", {"user": "", "token": ""}).login(image_name)
            assert cre.value.description == "Could not authenticate against the registry"

    def test_cr_metadata_empty(
            self,
            cr_class,
            registry,
            container
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is an empty dictionary
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                self.login_url,
                json={"token": "12345asdf"},
                status=200
            )
            rsps.add(
                responses.GET,
                self.tags_url % (registry.url, container.name),
                json={"results": []},
                status=200
            )
            assert {"name": container.name, "tag": [], "sha": []} == cr_class.get_image_tags(container.name)

    def test_cr_metadata_tag_not_in_api_response(
            self,
            cr_class,
            registry,
            container
    ):
        """
        Test that the Container registry helper behaves as expected when the
            tag is not in the list of the metadata info. Which is a `False`
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                self.login_url,
                json={"token": "12345asdf"},
                status=200
            )
            rsps.add(
                responses.GET,
                self.tags_url % (registry.url ,container.name),
                json={"results": [{"name": ["1.2.3", "dev"], "digest": "sha256:123ae123df"}]},
                status=200
            )
            assert not cr_class.has_image_tag_or_sha(container.name, "latest")

