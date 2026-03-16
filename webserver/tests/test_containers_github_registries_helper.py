import httpx
import responses
from pytest import mark, raises

from app.helpers.exceptions import ContainerRegistryException
from tests.fixtures.github_cr_fixtures import *


class TestGitHubRegistry:
    """
    Different registry classes make different requests.
        This addressed the github case, where login is not
        strictly a separate action
    """
    @mark.asyncio
    async def test_create_registry_with_no_org_fails(self):
        """
        GitHub Registry format is ghcr.io/organization
        without organization we shouldn't progress with init
        """
        invalid_names = ["ghcr.io", "ghcr.io/", "/ghcr.io"]
        for name in invalid_names:
            with raises(ContainerRegistryException) as cre:
                GitHubRegistry(registry=name)
            assert cre.value.description == "For GitHub registry, provide the org name. i.e. ghcr.io/orgname"

    @mark.asyncio
    async def test_cr_metadata_empty(
            self,
            container,
            cr_class,
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is a `False`
        """
        respx_mock.get(
            f"https://api.github.com/orgs/{cr_class.organization}/packages/container/{container.name}/versions"
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
            respx_mock
    ):
        """
        Test that the Container registry helper behaves as expected when the
            tag is not in the list of the metadata info. Which is a `False`
        """
        respx_mock.get(
            f"https://api.github.com/orgs/{cr_class.organization}/packages/container/{container.name}/versions"
        ).mock(
            return_value=httpx.Response(
                json=[{
                    "name": "sha256:123aed5143c5a15",
                    "metadata": {
                        "container":{
                            "tags": ["1.2.3", "dev"]
                        }
                    }
                }],
                status_code=200
            )
        )
        assert not await cr_class.has_image_tag_or_sha(container.name, "latest")

    @mark.asyncio
    async def test_list_repos(
        self,
        registry,
        cr_class,
        container,
        respx_mock
    ):
        """
        Tests that the expected github request can be re-formatted
        to the FN standard
        """
        respx_mock.get(
            f"https://api.github.com/orgs/{cr_class.organization}/packages?package_type=container",
        ).mock(
            return_value=httpx.Response(
                json=[{
                    "name": container.name
                }],
                status_code=200
            )
        )
        respx_mock.get(
            f"https://api.github.com/orgs/{cr_class.organization}/packages/container/{container.name}/versions"
        ).mock(
            return_value=httpx.Response(
                json=[{
                    "name": "sha256:123aed5143c5a15",
                    "metadata": {
                        "container":{
                            "tags": ["1.2.3", "dev"]
                        }
                    }
                }],
                status_code=200
            )
        )
        expected_list = [{
            "name": container.name,
            "tag": ["1.2.3", "dev"],
            "sha": ["sha256:123aed5143c5a15"]
        }]

        assert expected_list == await cr_class.list_repos()
