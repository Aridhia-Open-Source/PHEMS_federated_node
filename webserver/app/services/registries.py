import json
import logging
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.client.models.v1_secret import V1Secret
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.registry import Registry
from app.helpers.container_registries import BaseRegistry, DockerRegistry
from app.helpers.exceptions import InvalidRequest
from app.helpers.kubernetes import KubernetesClient
from app.helpers.settings import settings
from app.schemas.registries import RegistryCreate, RegistryUpdate


logger = logging.getLogger("registry_service")
logger.setLevel(logging.INFO)


class RegistryService:
    @staticmethod
    async def add(session:AsyncSession, data: RegistryCreate) -> Registry:
        q = select(Registry).where(Registry.url == data.url)
        if (await session.execute(q)).one_or_none():
            raise InvalidRequest(f"Registry {data.url} already exist")

        reg_data = data.model_dump()

        reg = Registry(**reg_data)
        _class: BaseRegistry = await reg.get_registry_class()
        await _class.login()
        try:
            await reg.update_regcred()
            await reg.add(session, False)
            await session.commit()
        except:
            await session.rollback()
            raise

        await session.refresh(reg)
        return reg

    @staticmethod
    async def update(session:AsyncSession, registry:Registry, data: RegistryUpdate) -> None:
        """
        Updates the instance with new values. These should be
        already validated.
        """
        if data.active is not None:
            await registry.update(session, {"active": data.active})

        if not(data.username or data.password):
            return

        # Get the credentials from the pull docker secret
        v1: KubernetesClient = await KubernetesClient.create()
        key = registry.url
        if isinstance(await registry.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"
        try:
            regcred: V1Secret = await v1.api_client.read_namespaced_secret(
                registry.slugify_name(), namespace=settings.task_namespace
            )
            dockerjson = json.loads(
                v1.decode_secret_value(regcred.data['.dockerconfigjson'])
            )
            registry.username = dockerjson['auths'][key]["username"]
            registry.password = dockerjson['auths'][key]["password"]

            if data.username:
                registry.username = data.username

            if data.password:
                registry.password = data.password

            await registry.update_regcred()
        except ApiException as apie:
            logger.error("Reason: %s\nDetails: %s", apie.reason, apie.body)
            raise InvalidRequest("Could not update credentials") from apie
