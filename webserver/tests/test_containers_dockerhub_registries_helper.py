import responses
from tests.fixtures.dockerhub_cr_fixtures import *
from app.helpers.exceptions import ContainerRegistryException


class TestDockerRegistry:
    """
    Different registry classes make different requests.
        This addressed the DockerHub case
    """
    login_url = "https://hub.docker.com/v2/users/login/"
    tags_url = "https://hub.docker.com/v2/repositories/%s/tags"

    def test_cr_login_failed(
            self,
            cr_class,
            container
    ):
        """
        Test that the Container registry helper behaves as expected when the login fails.
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                self.login_url,
                status=401
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.login(container.name)
            assert cre.value.description == "Could not authenticate against the registry"

    def test_cr_metadata_empty(
            self,
            cr_class,
            container
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is a `False`
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
                self.tags_url % container.name,
                json={"results": []},
                status=200
            )
            assert not cr_class.get_image_tags(container.name)

    def test_cr_metadata_tag_not_in_api_response(
            self,
            cr_class,
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
                self.tags_url % container.name,
                json={"results": [{"name": ["1.2.3", "dev"]}]},
                status=200
            )
            assert not cr_class.get_image_tags(container.name, "latest")

