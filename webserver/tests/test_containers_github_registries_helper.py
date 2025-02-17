import responses
from app.helpers.exceptions import ContainerRegistryException
from tests.fixtures.github_cr_fixtures import *


class TestGitHubRegistry:
    """
    Different registry classes make different requests.
        This addressed the github case, where login is not
        strictly a separate action
    """
    def test_create_registry_with_no_org_fails(self):
        """
        GitHub Registry format is ghcr.io/organization
        without organization we shouldn't progress with init
        """
        invalid_names = ["ghcr.io", "ghcr.io/", "/ghcr.io"]
        for name in invalid_names:
            with pytest.raises(ContainerRegistryException) as cre:
                GitHubRegistry(registry=name)
            assert cre.value.description == "For GitHub registry, provide the org name. i.e. ghcr.io/orgname"

    def test_cr_metadata_empty(
            self,
            container,
            cr_class
    ):
        """
        Test that the Container registry helper behaves as expected when the
            metadata response is empty. Which is a `False`
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://api.github.com/orgs/{cr_class.organization}/packages/container/{container.name}/versions",
                json=[],
                status=200
            )
            assert not cr_class.get_image_tags(container.name)

    def test_cr_metadata_tag_not_in_api_response(
            self,
            container,
            cr_class
    ):
        """
        Test that the Container registry helper behaves as expected when the
            tag is not in the list of the metadata info. Which is a `False`
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://api.github.com/orgs/{cr_class.organization}/packages/container/{container.name}/versions",
                json=[{
                    "metadata": {
                        "container":{
                            "tags": ["1.2.3", "dev"]
                        }
                    }
                }],
                status=200
            )
            assert not cr_class.get_image_tags(container.name, "latest")

    def test_list_repos(
        self,
        registry,
        cr_class,
        container
    ):
        """
        Tests that the expected github request can be re-formatted
        to the FN standard
        """
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"https://api.github.com/orgs/{cr_class.organization}/packages?package_type=container",
                json=[{
                    "name": container.name
                }],
                status=200
            )
            rsps.add(
                responses.GET,
                f"https://api.github.com/orgs/{cr_class.organization}/packages/container/{container.name}/versions",
                json=[{
                    "metadata": {
                        "container":{
                            "tags": ["1.2.3", "dev"]
                        }
                    }
                }],
                status=200
            )
            assert cr_class.list_repos() == [{"name": container.name, "tags": ["1.2.3", "dev"]}]
