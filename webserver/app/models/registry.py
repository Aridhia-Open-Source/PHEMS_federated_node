import base64
import json
import logging
import re
from kubernetes.client.exceptions import ApiException
from sqlalchemy import Column, Integer, String, Boolean

from app.helpers.const import TASK_NAMESPACE
from app.helpers.container_registries import AzureRegistry, BaseRegistry, DockerRegistry, GitHubRegistry
from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest
from app.helpers.kubernetes import KubernetesClient

logger = logging.getLogger("registry_model")
logger.setLevel(logging.INFO)


class Registry(db.Model, BaseModel):
    __tablename__ = 'registries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(256), nullable=False)
    needs_auth = Column(Boolean, default=True)
    active = Column(Boolean, default=True)

    def __init__(
            self,
            url: str,
            username: str,
            password: str,
            needs_auth:bool=True,
            active:bool=True
        ):
        self.url = url
        self.needs_auth = needs_auth
        self.active = active
        self.username = username
        self.password = password

    def sanitized_dict(self):
        san_dict = super().sanitized_dict()
        keys = list(san_dict.keys())
        for k in keys:
            if k not in self._get_fields_name():
                san_dict.pop(k, None)
        return san_dict

    @classmethod
    def validate(cls, data:dict):
        data = super().validate(data)

        # Test credentials
        _class = cls(**data).get_registry_class()
        _class.login()
        return data

    def _get_name(self):
        return re.sub('^http(s{,1})://', '', self.url)

    def add(self, commit=True):
        self.update_regcred()
        super().add(commit)

    def update_regcred(self):
        """
        Every time a new registry is added, a new docker config secret
        is created.
        """
        v1 = KubernetesClient()
        secret_name:str = self.slugify_name()
        dockerjson = dict()

        key = self.url
        if isinstance(self.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"

        try:
            secret = v1.read_namespaced_secret(secret_name, TASK_NAMESPACE)
        except ApiException as apie:
            if apie.status == 404:
                v1.create_secret(
                    name=secret_name,
                    values={".dockerconfigjson": json.dumps({"auths" : {}})},
                    namespaces=[TASK_NAMESPACE],
                    type='kubernetes.io/dockerconfigjson'
                )
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
        v1.patch_namespaced_secret(namespace=TASK_NAMESPACE, name=secret_name, body=secret)

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
        _class = self.get_registry_class()
        return _class.list_repos()

    def delete(self, commit:bool=False):
        session = db.session
        super().delete(commit)
        v1 = KubernetesClient()
        try:
            v1.delete_namespaced_secret(namespace=TASK_NAMESPACE, name=self.slugify_name())
        except ApiException as kae:
            session.rollback()
            logger.error("%s:\n\tDetails: %s", kae.reason, kae.body)
            raise ContainerRegistryException("Error while deleting entity")

    def update(self, **kwargs) -> None:
        """
        Updates the instance with new values. These should be
        already validated.
        """
        for key in kwargs.keys():
            if key not in ["username", "password", "active"]:
                raise InvalidRequest(f"Field {key} is not valid")

        if kwargs.get("active") is not None:
            self.query.filter(Registry.id == self.id).update(
                {"active": kwargs.get("active")},
                synchronize_session='evaluate'
            )

        if not(kwargs.get("username") or kwargs.get("password")):
            return

        # Get the credentials from the pull docker secret
        v1 = KubernetesClient()
        key = self.url
        if isinstance(self.get_registry_class(), DockerRegistry):
            key = "https://index.docker.io/v1/"
        try:
            regcred = v1.read_namespaced_secret(self.slugify_name(), namespace=TASK_NAMESPACE)
            dockerjson = json.loads(v1.decode_secret_value(regcred.data['.dockerconfigjson']))
            self.username = dockerjson['auths'][key]["username"]
            self.password = dockerjson['auths'][key]["password"]

            if kwargs.get("username"):
                self.username = kwargs.get("username")

            if kwargs.get("password"):
                self.password = kwargs.get("password")

            self.update_regcred()
        except ApiException as apie:
            logger.error("Reason: %s\nDetails: %s", apie.reason, apie.body)
            raise InvalidRequest("Could not update credentials") from apie
