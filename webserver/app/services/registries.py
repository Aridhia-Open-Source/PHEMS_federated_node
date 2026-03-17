import json
import logging
from kubernetes.client.exceptions import ApiException

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
    def add(data: RegistryCreate) -> Registry:
        reg_data = data.model_dump()
        reg = Registry(**reg_data)
        _class: BaseRegistry = reg.get_registry_class()
        _class.login()
        reg.update_regcred()
        reg.add()
        return reg

    @staticmethod
    def update(registry:Registry, data: RegistryUpdate) -> None:
        """
        Updates the instance with new values. These should be
        already validated.
        """
        if data.active is not None:
            registry.query.filter(Registry.id == registry.id).update(
                {"active": data.active},
                synchronize_session='evaluate'
            )

        if not(data.username or data.password):
            return

        # Get the credentials from the pull docker secret
        v1 = KubernetesClient()
        key = registry.url
        if isinstance(registry.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"
        try:
            regcred = v1.read_namespaced_secret(
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

            registry.update_regcred()
        except ApiException as apie:
            logger.error("Reason: %s\nDetails: %s", apie.reason, apie.body)
            raise InvalidRequest("Could not update credentials") from apie
