import httpx
from pytest import mark, raises
import responses
import requests
from tests.fixtures.azure_cr_fixtures import *
from app.helpers.exceptions import ContainerRegistryException


class TestAzureRegistry:
    """
    Different registry classes make different requests.
        This addressed the Azure case
    """
    @mark.asyncio
    async def test_cr_login_failed(
            self,
            container,
            cr_class,
            cr_name,
            registry,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the login fails.
        """
        respx_mock.get(
            f"https://{cr_name}/oauth2/token",
            params={
                "service": registry.url,
                "scope": f"repository:{container.name}:*"
            }
        ).mock(
            return_value=httpx.Response(
                status_code=401
            )
        )
        with raises(ContainerRegistryException) as cre:
            cr_class.login(container.name)
        assert cre.value.description == "Could not authenticate against the registry"

    @mark.asyncio
    async def test_cr_metadata_empty(
            self,
            container,
            cr_class,
            cr_name,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is a `False`
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
                json=[],
                status_code=200
            )
        )
        assert await cr_class.get_image_tags(container.name) == {'tag': [], 'sha': []}

    @mark.asyncio
    async def test_cr_metadata_tag_not_in_api_response(
            self,
            container,
            cr_class,
            cr_name,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the
            tag is not in the list of the metadata info. Which is a `False`
        """
        expected_tags = ["1.2.3", "dev"]
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
                json={"tags": expected_tags},
                status_code=200
            )
        )
        for t in expected_tags:
            respx_mock.get(
                f"https://{cr_name}/v2/{container.name}/manifests/{t}"
            ).mock(
                return_value=httpx.Response(
                    json={"config": {"digest": "sha256:123123123"}},
                    status_code=200
                )
            )
        assert not await cr_class.has_image_tag_or_sha(container.name, "latest")

    @mark.asyncio
    async def test_cr_login_connection_error(
        self,
        registry,
        cr_class,
        respx_mock
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during a login. The exception
        should be the same regardless of the cr class
        Github's, Azure's or Docker's.
        """
        respx_mock.get(
            f"https://{registry.url}/oauth2/token",
            params={
                "service": registry.url,
                "scope": "registry:catalog:*"
            }
        ).mock(
            side_effect=[
                requests.ConnectionError("error")
            ]
        )
        with raises(ContainerRegistryException) as cre:
            cr_class.login()
        assert cre.value.description == "Failed to connect with the Registry. Make sure it's spelled correctly or it does not have firewall restrictions."

    @mark.asyncio
    async def test_cr_tags_connection_error(
        self,
        registry,
        cr_name,
        container,
        cr_class,
        respx_mock
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the container tags list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        respx_mock.get(
            f"https://{cr_name}/v2/{container.name}/tags/list"
        ).mock(
            side_effect=[requests.ConnectionError("error")]
        )
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
        with raises(ContainerRegistryException) as cre:
            await cr_class.get_image_tags(container.name)
        assert cre.value.description == f"Failed to fetch the list of tags from {registry.url}/{container.name}"

    @mark.asyncio
    async def test_cr_tags_request_fails(
        self,
        registry,
        cr_name,
        container,
        cr_class,
        respx_mock
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the container tags list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        respx_mock.get(
            f"https://{cr_name}/v2/{container.name}/tags/list"
        ).mock(
            return_value=httpx.Response(
                json={"error": "Something went wrong"},
                status_code=400
            )
        )
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
        with raises(ContainerRegistryException) as cre:
            await cr_class.get_image_tags(container.name)
        assert cre.value.description == f"Failed to fetch the list of tags for {container.name}"

    @mark.asyncio
    async def test_cr_list_repo_connection_error(
        self,
        registry,
        cr_name,
        cr_class,
        respx_mock
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the fetching of the container list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        respx_mock.get(
            f"https://{cr_name}/v2/_catalog"
        ).mock(
            side_effect=[requests.ConnectionError("error")]
        )
        with raises(ContainerRegistryException) as cre:
            await cr_class.list_repos()
        assert cre.value.description == f"Failed to fetch the list of available containers from {registry.url}"

    @mark.asyncio
    async def test_cr_list_repo_request_fails(
        self,
        registry,
        cr_name,
        cr_class,
        respx_mock
    ):
        """
        Checks that we handle a ConnectionError
        exception properly during the fetching of the container list.
        The exception should be re-raised as a custom one, so that
        flask can return a formatted error
        """
        respx_mock.get(
            f"https://{cr_name}/v2/_catalog"
        ).mock(
            return_value=httpx.Response(
                json={"error": "Something went wrong"},
                status_code=400
            )
        )
        with raises(ContainerRegistryException) as cre:
            await cr_class.list_repos()
        assert cre.value.description == "Could not fetch the list of images"
