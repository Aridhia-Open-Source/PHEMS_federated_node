import json
import logging
import re
from typing import TYPE_CHECKING, List
from kubernetes.client.exceptions import ApiException
from sqlalchemy import Integer, String, Boolean
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship
from sqlalchemy.orm.properties import MappedColumn

from app.helpers.settings import settings
from app.helpers.container_registries import AzureRegistry, BaseRegistry, DockerRegistry, GitHubRegistry
from app.helpers.base_model import BaseModel
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest
from app.helpers.kubernetes import KubernetesClient

if TYPE_CHECKING:
    from .container import Container

logger = logging.getLogger("registry_model")
logger.setLevel(logging.INFO)


class Registry(BaseModel):
    __tablename__ = 'registries'

    id: MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: MappedColumn[str] = mapped_column(String(256), nullable=False)
    needs_auth: MappedColumn[bool] = mapped_column(Boolean, default=True)
    active: MappedColumn[bool] = mapped_column(Boolean, default=True)

    containers: Mapped[List["Container"]] = relationship(
        "Container",
        back_populates="registry",
        cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        self.username = kwargs.pop("username", None)
        self.password = kwargs.pop("password", None)
        super().__init__(**kwargs)

    def _get_name(self):
        return re.sub('^http(s{,1})://', '', self.url)

    def update_regcred(self):
        """
        Every time a new registry is added, a new docker config secret
        is created.
        """
        v1 = KubernetesClient()
        secret_name:str = self.slugify_name()
        dockerjson = {}

        key = self.url
        if isinstance(self.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"

        try:
            secret = v1.read_namespaced_secret(secret_name, settings.task_namespace)
        except ApiException as apie:
            if apie.status == 404:
                v1.create_secret(
                    name=secret_name,
                    values={".dockerconfigjson": json.dumps({"auths" : {}})},
                    namespaces=[settings.task_namespace],
                    type='kubernetes.io/dockerconfigjson'
                )
                secret = v1.read_namespaced_secret(secret_name, settings.task_namespace)
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
        v1.patch_namespaced_secret(namespace=settings.task_namespace, name=secret_name, body=secret)

    def _get_creds(self):
        if hasattr(self, "username") and hasattr(self, "password"):
            return {"user": self.username, "token": self.password}

    def slugify_name(self) -> str:
        """
        Based on the provided name, it will return the slugified name
        so that it will be sade to save on the DB
        """
        return re.sub(r'[\W_]+', '-', self._get_name())

    def get_registry_class(self) -> BaseRegistry:
        """
        We have interface classes with dedicated login, and
        image tag parsers. Based on the registry name
        infers the appropriate class
        """
        args = {
            "registry": self._get_name(),
            "creds": self._get_creds()
        }
        if self.id:
            args["secret_name"]= self.slugify_name()
        matches = re.search(r'azurecr\.io|ghcr\.io', self.url)

        matches = '' if matches is None else matches.group()

        match matches:
            case 'azurecr.io':
                return AzureRegistry(**args)
            case 'ghcr.io':
                return GitHubRegistry(**args)
            case _:
                return DockerRegistry(**args)

    def fetch_image_list(self) -> list[str]:
        """
        Simply returns a list of strings of all available
            images (or repos) with their tags
        """
        _class: BaseRegistry = self.get_registry_class()
        return _class.list_repos()

    def delete(self, session: Session):
        nested = session.begin_nested()
        super().delete(session, False)
        v1 = KubernetesClient()
        try:
            v1.delete_namespaced_secret(namespace=settings.task_namespace, name=self.slugify_name())
        except ApiException as apie:
            nested.rollback()
            logger.error("%s:\n\tDetails: %s", apie.reason, apie.body)
            raise ContainerRegistryException("Error while deleting entity")
