import json
import logging
import re

from kubernetes.client.exceptions import ApiException
from sqlalchemy import Column, Integer, String, Boolean

from app.helpers.const import TASK_NAMESPACE
from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest
from app.helpers.kubernetes import KubernetesClient
from app.helpers import container_registries


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
        needs_auth: bool = True,
        active: bool = True
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
        return re.sub(r'^https?://', '', self.url)  # type: ignore

    def add(self, commit=True):
        self.update_regcred()
        super().add(commit)

    def update_regcred(self):
        """
        Every time a new registry is added, a new docker config secret
        is created.
        """
        v1 = KubernetesClient()
        secret_name: str = self.slugify_name()
        dockerjson = dict()

        key = self.url
        if isinstance(self.get_registry_class(), container_registries.DockerRegistry):
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
                secret = v1.read_namespaced_secret(secret_name, TASK_NAMESPACE)
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

    def get_registry_class(self):
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

        matches = re.search(r'azurecr\.io|ghcr\.io', self.url)  # type: ignore
        matches = '' if matches is None else matches.group()

        match matches:
            case 'azurecr.io':
                return container_registries.AzureRegistry(**args)
            case 'ghcr.io':
                return container_registries.GitHubRegistry(**args)
            case _:
                return container_registries.DockerRegistry(**args)

    def fetch_image_list(self) -> list[str]:
        """
        Simply returns a list of strings of all available
            images (or repos) with their tags
        """
        _class = self.get_registry_class()
        return _class.list_repos()

    def delete(self, commit: bool = False):
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
        Updates the instance with new values. These should be already validated.
        """
        for key in kwargs.keys():
            if key not in ["username", "password", "active"]:
                raise InvalidRequest(f"Field {key} is not valid")
            if kwargs[key] is None:
                raise InvalidRequest(f"Field {key} cannot be None")

        if kwargs.get("active"):
            query = self.query.filter(Registry.id == self.id)
            query.update({"active": kwargs.get("active")}, synchronize_session='evaluate')

        if not kwargs.get("username") and not kwargs.get("password"):
            return

        self.update_username_password(kwargs.get("username"), kwargs.get("password"))

        self.update_regcred()

    def update_username_password(
        self,
        username: str | None,
        password: str | None
    ) -> None:
        """
        Updates the instance with new username and password values
        """
        v1 = KubernetesClient()
        reg_class = self.get_registry_class()
        is_docker_reg = isinstance(reg_class, container_registries.DockerRegistry)
        key = self.url if not is_docker_reg else "https://index.docker.io/v1/"

        regcred = v1.read_namespaced_secret(self.slugify_name(), TASK_NAMESPACE)
        secret_val = regcred.data['.dockerconfigjson']  # type: ignore
        dockerjson = json.loads(v1.decode_secret_value(secret_val))
        self.username = dockerjson['auths'][key]["username"]
        self.password = dockerjson['auths'][key]["password"]

        if username:
            self.username = username
        if password:
            self.password = password


    @classmethod
    def extract_image_parts(
        cls,
        docker_image: str
    ) -> tuple['Registry', str, str | None, str | None]:
        """
        Extract the registry object, image name, tag, and sha from the docker image str.
        """
        for i in range(len(docker_image.split('/')) + 1):
            registry_url = "/".join(docker_image.split('/')[0:i])
            registry = Registry.query.filter_by(url=registry_url).one_or_none()
            if registry:
                image_path = "/".join(docker_image.split('/')[i:])
                tag = None
                sha = None
                if '@' in image_path:
                    image_name, sha = image_path.split('@')
                    if ':' in image_name:
                        image_name, tag = image_name.split(':')
                elif ':' in image_path:
                    image_name, tag = image_path.split(':')
                else:
                    raise InvalidRequest(f"Image {docker_image} must have a tag or a sha")
                return registry, image_name, tag, sha

        raise InvalidRequest(
            "Could not find the image in the mapped registries."
            " Check the image has the full name"
        )

    @classmethod
    def validate_image_exist(cls, docker_image: str) -> bool:
        """
        Validate that the image exists in the remote registry.
        """
        registry, image_name, tag, sha = cls.extract_image_parts(docker_image)
        registry_client = registry.get_registry_class()
        if not registry_client.has_image_tag_or_sha(image_name, tag, sha):
            return False
        return True
