import responses
import requests
from tests.fixtures.azure_cr_fixtures import *
from app.helpers.exceptions import ContainerRegistryException


class TestAzureRegistry:
    """
    Different registry classes make different requests.
        This addressed the Azure case
    """
    def test_cr_login_failed(
            self,
            container,
            cr_class,
            cr_name,
            registry
    ):
        """
        Test that the Container registry helper behaves as expected when the login fails.
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/oauth2/token?service={registry.url}&scope=repository:{container.name}:metadata_read",
                status=401
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.login(container.name)
            assert cre.value.description == "Could not authenticate against the registry"

    def test_cr_metadata_empty(
            self,
            container,
            cr_class,
            cr_name
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is a `False`
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{container.name}:metadata_read",
                json={"access_token": "12345asdf"},
                status=200
            )
            rsps.add(
                responses.GET,
                f"https://{cr_name}/v2/{container.name}/tags/list",
                json=[],
                status=200
            )
            assert not cr_class.get_image_tags(container.name)

    def test_cr_metadata_tag_not_in_api_response(
            self,
            container,
            cr_class,
            cr_name
    ):
        """
        Test that the Container registry helper behaves as expected when the
            tag is not in the list of the metadata info. Which is a `False`
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{container.name}:metadata_read",
                json={"access_token": "12345asdf"},
                status=200
            )
            rsps.add(
                responses.GET,
                f"https://{cr_name}/v2/{container.name}/tags/list",
                json={"tags": ["1.2.3", "dev"]},
                status=200
            )
            assert not cr_class.get_image_tags(container.name, "latest")

    def test_cr_login_connection_error(
        self,
        registry,
        cr_class
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during a login. The exception
        should be the same regardless of the cr class
        Github's, Azure's or Docker's.
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{registry.url}/oauth2/token?service={registry.url}&scope=registry:catalog:*",
                body=requests.ConnectionError("error")
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.login()
        assert cre.value.description == "Failed to connect with the Registry. Make sure it's spelled correctly or it does not have firewall restrictions."

    def test_cr_tags_connection_error(
        self,
        registry,
        cr_name,
        container,
        cr_class
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the container tags list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/v2/{container.name}/tags/list",
                body=requests.ConnectionError("error")
            )
            rsps.add(
                responses.GET,
                f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{container.name}:metadata_read",
                json={"access_token": "12345asdf"},
                status=200
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.get_image_tags(container.name)
            assert cre.value.description == f"Failed to fetch the list of tags from {registry.url}/{container.name}"

    def test_cr_tags_request_fails(
        self,
        registry,
        cr_name,
        container,
        cr_class
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the container tags list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/v2/{container.name}/tags/list",
                json={"error": "Something went wrong"},
                status=400
            )
            rsps.add(
                responses.GET,
                f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{container.name}:metadata_read",
                json={"access_token": "12345asdf"},
                status=200
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.get_image_tags(container.name)
            assert cre.value.description == f"Failed to fetch the list of tags for {container.name}"

    def test_cr_list_repo_connection_error(
        self,
        registry,
        cr_name,
        cr_class
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the fetching of the container list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/v2/_catalog",
                body=requests.ConnectionError("error")
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.list_repos()
            assert cre.value.description == f"Failed to fetch the list of available containers from {registry.url}"

    def test_cr_list_repo_request_fails(
        self,
        registry,
        cr_name,
        cr_class
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the fetching of the container list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://{cr_name}/v2/_catalog",
                json={"error": "Something went wrong"},
                status=400
            )
            with pytest.raises(ContainerRegistryException) as cre:
                cr_class.list_repos()
            assert cre.value.description == "Could not fetch the list of images"
