from base64 import b64encode
import httpx
from typing import List, Self
import logging
from requests.exceptions import ConnectionError

from app.helpers.exceptions import ContainerRegistryException


logger = logging.getLogger('registries_handler')
logger.setLevel(logging.INFO)


class BaseRegistry:
    token_field = None
    login_url = None
    repo_login_url = None
    list_repo_url = None
    creds = None
    organization = ''
    request_args = {}
    api_login = True
    list_req_params = {"page": 1, "page_size": 100}

    def __init__(self, registry:str, creds:dict={}):
        self.registry = registry
        self.creds = creds

    @classmethod
    async def create(cls, registry:str, creds:dict={}) -> Self:
        instance: Self = cls(registry, creds)
        await instance.login()
        return instance

    async def list_repos(self) -> list[str]:
        """
        Depending on the provider, will need to run
            different api requests to get a list of
            available images
        """
        try:
            async with httpx.AsyncClient() as requests:
                list_resp: httpx.Response = await requests.get(
                    self.list_repo_url % {"service": self.registry, "organization": self.organization},
                    headers={"Authorization": f"Bearer {self._token}"}
                )
            if list_resp.is_error:
                logger.error(list_resp.text)
                raise ContainerRegistryException("Could not fetch the list of images", 500)
        except ConnectionError as ce:
            raise ContainerRegistryException(
                f"Failed to fetch the list of available containers from {self.registry}",
                500
            ) from ce
        return list_resp.json()

    async def login(self, image:str=None) -> str:
        """
        Check that credentials are valid (if image is None)
            else, exchanges credentials for a token with the image or repo scope
        """
        url = self.repo_login_url if image else  self.login_url
        try:
            # TODO: Find a way to make it async since we use it in a constructor
            async with httpx.AsyncClient() as requests:
                response_auth: httpx.Response = await requests.get(
                    url % self.get_url_string_params(image_name=image),
                    **self.request_args
                )

            if response_auth.is_error:
                logger.info(response_auth.text)
                raise ContainerRegistryException("Could not authenticate against the registry", 400)

            self._token = response_auth.json()[self.token_field]
        except ConnectionError as ce:
            raise ContainerRegistryException(
                "Failed to connect with the Registry. Make sure it's spelled correctly"
                " or it does not have firewall restrictions.",
                500
            ) from ce

    def get_url_string_params(self, image_name:str=None) -> dict[str,str]:
        return {
            "service": self.registry,
            "image": image_name or '',
            "organization": self.organization
        }

    async def get_image_tags(self, image:str) -> dict[str, str|List[str]]:
        """
        Works as an existence check. If the tag for the image
        has the requested tag in the list of available tags
        return True.
        This should work on any docker Registry v2 as it's a standard
        """
        try:
            async with httpx.AsyncClient() as requests:
                response_metadata: httpx.Response = await requests.get(
                    self.tags_url % self.get_url_string_params(image_name=image),
                    params=self.list_req_params,
                    headers={"Authorization": f"Bearer {self._token}"}
                )
            if response_metadata.is_error:
                logger.info(response_metadata.text)
                raise ContainerRegistryException(f"Failed to fetch the list of tags for {image}")

            return response_metadata.json()
        except ConnectionError as ce:
            raise ContainerRegistryException(
                f"Failed to fetch the list of tags from {self.registry}/{image}",
                500
            ) from ce

    async def has_image_tag_or_sha(self, image:str, tag:str=None, sha:str=None) -> bool:
        """
        Based on get_image_tags, checks if a tag is available
        """
        tags_list = await self.get_image_tags(image)
        if not tags_list:
            return False

        return tag in tags_list["tag"] or sha in tags_list["sha"]


class AzureRegistry(BaseRegistry):
    # https://docker-docs.uclv.cu/registry/spec/api for api schemas
    login_url = "https://%(service)s/oauth2/token?service=%(service)s&scope=registry:catalog:*"
    repo_login_url = "https://%(service)s/oauth2/token?service=%(service)s&scope=repository:%(image)s:*"
    tags_url = "https://%(service)s/v2/%(image)s/tags/list"
    digest_url = "https://%(service)s/v2/%(image)s/manifests/"
    list_repo_url = "https://%(service)s/v2/_catalog"
    token_field = "access_token"
    list_req_params = {"n": 100}

    @classmethod
    async def create(cls, registry:str, creds:dict={}) -> Self:
        instance = await super().create(registry, creds)
        instance.auth = b64encode(f"{creds['user']}:{creds['token']}".encode()).decode()
        instance.request_args["headers"] = {"Authorization": f"Basic {instance.auth}"}
        return instance

    async def get_image_digest(self, image:str, tag:str) -> dict[str, str]:
        try:
            async with httpx.AsyncClient() as requests:
                response_metadata = await requests.get(
                    self.digest_url % self.get_url_string_params(image_name=image) + tag,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.docker.distribution.manifest.v2+json"
                    }
                )

            if response_metadata.is_error:
                logger.info(response_metadata.text)
                raise ContainerRegistryException(f"Failed to fetch the list of digest for {image}")

            return response_metadata.json()["config"]["digest"]
        except ConnectionError as ce:
            raise ContainerRegistryException(
                f"Failed to fetch the list of digest from {self.registry}/{image}",
                500
            ) from ce

    async def get_image_tags(self, image:str) -> dict[str, str|List[str]]:
        tags_list = await super().get_image_tags(image)
        full_tags = {"tag": [], "sha": []}

        if tags_list:
            full_tags["tag"] = [t for t in tags_list.get("tags", [])]

            for t in full_tags["tag"]:
                full_tags["sha"] = [await self.get_image_digest(image, t)]

        return full_tags

    async def list_repos(self) -> List[dict[str, str | List[str]]]:
        list_images = await super().list_repos()
        images = []
        for image in list_images["repositories"]:
            properties = {"name": image}
            properties.update(await self.get_image_tags(image))
            images.append(properties)
        return images


class DockerRegistry(BaseRegistry):
    # https://docs.docker.com/reference/api/hub/latest/#tag/repositories
    repo_login_url = "https://hub.docker.com/v2/users/login/"
    login_url = "https://hub.docker.com/v2/users/login/"
    tags_url = "https://hub.docker.com/v2/namespaces/%(organization)s/repositories/%(image)s/tags"
    list_repo_url = "https://hub.docker.com/v2/repositories/%(organization)s"
    token_field = "token"

    @classmethod
    async def create(cls, registry:str, creds:dict={}) -> Self:
        instance = await super().create(registry, creds)
        instance.auth = b64encode(f"{creds['user']}:{creds['token']}".encode()).decode()
        instance.request_args["headers"] = {"Authorization": f"Basic {instance.auth}"}


        instance.organization = registry
        instance.request_args["auth"] = (creds['user'], creds['token'])
        instance.request_args["headers"] = {"Content-Type": "application/json"}
        await instance.login()
        return instance

    async def get_image_tags(self, image:str) -> dict[str, str|List[str]]:
        tags_list = await super().get_image_tags(image)

        metadata = {"name": image, "tag": [], "sha": []}
        for t in tags_list["results"]:
            metadata["tag"].append(t["name"])
            metadata["sha"].append(t["digest"])

        return metadata

    async def list_repos(self) -> List[dict[str, str | List[str]]]:
        list_images = await super().list_repos()
        return [await self.get_image_tags(image["name"]) for image in list_images["results"]]


class GitHubRegistry(BaseRegistry):
    login_url = None
    api_login = False
    tags_url = "https://api.github.com/orgs/%(organization)s/packages/container/%(image)s/versions"
    list_repo_url = "https://api.github.com/orgs/%(organization)s/packages?package_type=container"
    list_req_params = {"page": 1, "per_page": 100}

    @classmethod
    async def create(cls, registry:str, creds:dict={}) -> Self:
        destruct_reg = registry.split('/', maxsplit=1)

        # Remove empty strings
        if '' in destruct_reg:
            destruct_reg.remove('')

        if len(destruct_reg) <= 1:
            raise ContainerRegistryException("For GitHub registry, provide the org name. i.e. ghcr.io/orgname")

        instance = await super().create(registry, creds)

        instance.request_args["headers"] = {}
        instance.organization = registry.split('/')[1]
        await instance.login()
        return instance

    async def login(self, image:str=None) -> str:
        logging.info("Auth on github skipped, an organization name is needed")
        self._token = self.creds['token']

    async def get_image_tags(self, image:str) -> dict[str, str|List[str]]:
        """
        Works as a list of available tags/sha. Limiting to only 100 tags per
        image
        """
        tags_list = []

        try:
            async with httpx.AsyncClient() as requests:
                response_metadata: httpx.Response = await requests.get(
                    self.tags_url % self.get_url_string_params(image_name=image),
                    params=self.list_req_params,
                    headers={"Authorization": f"Bearer {self._token}"}
                )
            if response_metadata.is_error:
                logger.info(response_metadata.text)
                raise ContainerRegistryException(f"Failed to fetch the list of tags for {image}")

            tags_list += response_metadata.json()

        except ConnectionError as ce:
            raise ContainerRegistryException(
                f"Failed to fetch the list of tags from {self.registry}/{image}",
                500
            ) from ce

        t_list = []
        s_list = []
        for tags in tags_list:
            if isinstance(tags["metadata"]["container"]["tags"], list):
                t_list += tags["metadata"]["container"]["tags"]
            else:
                t_list.append(tags["metadata"]["container"]["tags"])
            s_list.append(tags["name"])

        return {"tag": t_list,"sha": s_list}

    async def list_repos(self) -> List[dict[str, str | List[str]]]:
        list_images = await super().list_repos()
        images = []
        for img in list_images:
            properties = {"name": img["name"]}
            properties.update(await self.get_image_tags(img["name"]))
            images.append(properties)
        return images
