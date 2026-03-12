import json
import logging
import re
from typing import NoReturn
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.client.models.v1_secret import V1Secret
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import AsyncSession

from app.helpers.const import TASK_NAMESPACE
from app.helpers.container_registries import AzureRegistry, BaseRegistry, DockerRegistry, GitHubRegistry
from app.helpers.base_model import BaseModel
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest
from app.helpers.kubernetes import KubernetesClient

logger = logging.getLogger("registry_model")
logger.setLevel(logging.INFO)


class Registry(BaseModel):
    __tablename__ = 'registries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(256), nullable=False)
    needs_auth = Column(Boolean, default=True)
    active = Column(Boolean, default=True)

    container = relationship("Container", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        self.username = kwargs.pop("username", None)
        self.password = kwargs.pop("password", None)
        super().__init__(**kwargs)

    def _get_name(self):
        return re.sub('^http(s{,1})://', '', self.url)

    async def update_regcred(self):
        """
        Every time a new registry is added, a new docker config secret
        is created.
        """
        v1: KubernetesClient = await KubernetesClient.create()
        secret_name:str = self.slugify_name()
        dockerjson = {}

        key = self.url
        if isinstance(await self.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"

        try:
            secret: V1Secret = await v1.api_client.read_namespaced_secret(secret_name, TASK_NAMESPACE)
        except ApiException as apie:
            if apie.status == 404:
                v1.create_secret(
                    name=secret_name,
                    values={".dockerconfigjson": json.dumps({"auths" : {}})},
                    namespaces=[TASK_NAMESPACE],
                    type='kubernetes.io/dockerconfigjson'
                )
                secret = await v1.api_client.read_namespaced_secret(secret_name, TASK_NAMESPACE)
            else:
                raise InvalidRequest("Something went wrong when creating registry secrets")

        dockerjson = json.loads(v1.decode_secret_value(secret.data['.dockerconfigjson']))
        dockerjson['auths'] = {
            key: {
                "username": self.username,
                "password": self.password,
                "email": "",
                "auth": v1.encode_secret_value(f"{self.username}:{self.password}")
            }
        }
        secret.data['.dockerconfigjson'] = v1.encode_secret_value(json.dumps(dockerjson))
        await v1.api_client.patch_namespaced_secret(namespace=TASK_NAMESPACE, name=secret_name, body=secret)

    async def _get_creds(self):
        if hasattr(self, "username") and hasattr(self, "password"):
            return {"user": self.username, "token": self.password}

        v1: KubernetesClient = await KubernetesClient.create()
        regcred = await v1.api_client.read_namespaced_secret(self.slugify_name(), TASK_NAMESPACE, pretty='pretty')

        dockerjson = json.loads(v1.decode_secret_value(regcred.data['.dockerconfigjson']))
        key = list(dockerjson["auths"].keys())[0]
        return {
            "user": dockerjson['auths'][key]["username"],
            "token": dockerjson['auths'][key]["password"]
        }

    def slugify_name(self) -> str:
        """
        Based on the provided name, it will return the slugified name
        so that it will be sade to save on the DB
        """
        return re.sub(r'[\W_]+', '-', self._get_name())

    async def get_registry_class(self) -> BaseRegistry:
        """
        We have interface classes with dedicated login, and
        image tag parsers. Based on the registry name
        infers the appropriate class
        """
        args = {
            "registry": self._get_name(),
            "creds": await self._get_creds()
        }
        matches = re.search(r'azurecr\.io|ghcr\.io', self.url)

        matches = '' if matches is None else matches.group()

        match matches:
            case 'azurecr.io':
                return AzureRegistry(**args)
            case 'ghcr.io':
                return GitHubRegistry(**args)
            case _:
                return DockerRegistry(**args)

    async def fetch_image_list(self) -> list[str]:
        """
        Simply returns a list of strings of all available
            images (or repos) with their tags
        """
        _class = await self.get_registry_class()
        return await _class.list_repos()

    async def delete(self, session: AsyncSession) -> NoReturn:
        async with session.begin_nested() as nested:
            await super().delete(session, False)
            v1: KubernetesClient = await KubernetesClient.create()
            try:
                await v1.api_client.delete_namespaced_secret(namespace=TASK_NAMESPACE, name=self.slugify_name())
            except ApiException as apie:
                await nested.rollback()
                logger.error("%s:\n\tDetails: %s", apie.reason, apie.body)
                raise ContainerRegistryException("Error while deleting entity")

    async def update(self, session:AsyncSession, data: dict):
        """
        Updates the instance with new values. These should be
        already validated.
        """
        if data.get("active") is not None:
            await super().update(session, {"active": data.get("active")})

        if not(data.get("username") or data.get("password")):
            return

        # Get the credentials from the pull docker secret
        v1: KubernetesClient = await KubernetesClient.create()
        key = self.url
        if isinstance(await self.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"
        try:
            regcred = await v1.api_client.read_namespaced_secret(self.slugify_name(), namespace=TASK_NAMESPACE)
            dockerjson = json.loads(v1.decode_secret_value(regcred.data['.dockerconfigjson']))
            self.username = dockerjson['auths'][key]["username"]
            self.password = dockerjson['auths'][key]["password"]

            if data.get("username"):
                self.username = data.get("username")

            if data.get("password"):
                self.password = data.get("password")

            await self.update_regcred()
        except ApiException as apie:
            logger.error("Reason: %s\nDetails: %s", apie.reason, apie.body)
            raise InvalidRequest("Could not update credentials") from apie
