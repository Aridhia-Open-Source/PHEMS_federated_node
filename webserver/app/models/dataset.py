import logging
import re
import typing
import urllib.parse
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE, PUBLIC_URL
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, KubernetesException
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from kubernetes.client import V1Secret
from kubernetes.client.exceptions import ApiException

from app.helpers.connection_string import Mssql, Postgres, Mysql, Oracle, MariaDB
from app.models import Models

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)

SUPPORTED_ENGINES = {
    "mssql": Mssql,
    "postgres": Postgres,
    "mysql": Mysql,
    "oracle": Oracle,
    "mariadb": MariaDB
}


class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, default=5432)
    schema = Column(String(256), nullable=True)
    schema_write = Column(String(256), nullable=True)
    type = Column(String(256), server_default="postgres", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)
    project_id = Column(
        Integer, ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project = relationship(
        "Project", back_populates="datasets", foreign_keys=[project_id]
    )

    def __init__(
        self,
        name: str,
        host: str,
        username: str,
        password: str,
        port: int = 5432,
        schema: str | None = None,
        schema_write: str | None = None,
        type: str = "postgres",
        extra_connection_args: str | None = None,
        project_id: int | None = None,
        **kwargs
    ):
        self.name = urllib.parse.unquote(name).lower()
        self.slug = self.slugify_name()
        self.url = f"https://{PUBLIC_URL}/datasets/{self.slug}"
        self.host = host
        self.port = port
        self.schema = schema
        self.schema_write = schema_write
        self.type = type
        self.username = username
        self.password = password
        self.extra_connection_args = extra_connection_args
        self.project_id = project_id

        if self.type.lower() not in SUPPORTED_ENGINES:
            raise InvalidRequest(f"DB type {self.type} is not supported.")

    def __repr__(self):
        return f'<Dataset {self.name}>'

    def add(self, commit=True, user_id=None):
        super().add(commit)
        # First dataset into a project becomes what a task gets when it names only the
        # project. Later ones do not displace it.
        project = Models.Project.get_by_id(self.project_id)
        if project.default_dataset_id is None:
            project.default_dataset_id = self.id
            project.add(commit)
        self.create_kubernetes_secret()
        delattr(self, "username")
        delattr(self, "password")
        self.add_to_keycloak(user_id)
        return self

    @classmethod
    def validate(cls, data: dict) -> dict:
        data = dict(data)  # prevent mutation
        return super().validate(data)

    @classmethod
    def parse_repo_uri(cls, uri: str) -> str:
        """
        Parse the repository URI to extract the host and path.
        """
        parsed = urllib.parse.urlparse(uri)
        return (parsed.netloc + parsed.path).lower().rstrip('/')

    def get_creds_secret_name(self, host=None, name=None):
        host = host or self.host
        name = name or self.name

        cleaned_up_host = re.sub('http(s)*://', '', host)
        return f"{cleaned_up_host}-{re.sub('\\s|_|#', '-', name.lower())}-creds"

    def get_connection_string(self):
        """
        From the helper classes, return the correct connection string
        """
        un, passw = self.get_credentials()
        return SUPPORTED_ENGINES[str(self.type)](
            user=un,
            passw=passw,
            host=self.host,
            port=self.port,
            database=self.name,
            args=self.extra_connection_args
        ).connection_str

    def sanitized_dict(self):
        dataset = super().sanitized_dict()
        dataset["slug"] = self.slugify_name()
        dataset["url"] = f"https://{PUBLIC_URL}/datasets/{dataset['slug']}"
        return dataset

    def slugify_name(self) -> str:
        """
        Based on the provided name, it will return the slugified name
        so that it will be sade to save on the DB
        """
        return re.sub(r'[\W_]+', '-', self.name)

    def get_credentials(self) -> tuple:
        """
        Mostly used to create a direct connection to the DB
        This is not involved in the Task Execution Service
        """
        secret = self._get_secret(self.get_creds_secret_name())
        if secret.data is None:
            raise ValueError("Secret data is None")

        user = KubernetesClient.decode_secret_value(secret.data['USERNAME'])
        password = KubernetesClient.decode_secret_value(secret.data['PASSWORD'])

        return user, password

    def create_kubernetes_secret(self) -> V1Secret:
        v1 = KubernetesClient()
        return v1.create_secret(
            name=self.get_creds_secret_name(),
            values={
                "USERNAME": self.username,
                "PASSWORD": self.password,
            },
            namespaces=[DEFAULT_NAMESPACE, TASK_NAMESPACE],
            # The labels update_kubernetes_secret already sets, so a secret reads the
            # same whether it was created or updated last. Teardown selects on them to
            # clear the ones the Helm release does not own.
            labels={
                "type": "database",
                "host": self.get_creds_secret_name()
            },
            # Registering a dataset is what decides its credentials. Without this the
            # create is refused as a conflict whenever a secret from a previous
            # registration is still around - silently, so the dataset row is new while
            # the password behind it is the old one, and the failure surfaces only much
            # later as an authentication error inside a task pod.
            overwrite=True
        )

    def add_to_keycloak(self, user_id=None):
        kc_client = Keycloak()
        admin_policy = kc_client.get_policy('admin-policy')
        sys_policy = kc_client.get_policy('system-policy')

        admin_ds_scope = []
        admin_ds_scope.append(kc_client.get_scope('can_admin_dataset'))
        admin_ds_scope.append(kc_client.get_scope('can_access_dataset'))
        admin_ds_scope.append(kc_client.get_scope('can_exec_task'))
        admin_ds_scope.append(kc_client.get_scope('can_admin_task'))
        admin_ds_scope.append(kc_client.get_scope('can_send_request'))
        admin_ds_scope.append(kc_client.get_scope('can_admin_request'))
        policy = kc_client.create_policy({
            "name": f"{self.id} - {self.name} Admin Policy",
            "description": f"List of users allowed to administrate the {self.name} dataset",
            "logic": "POSITIVE",
            "users": [user_id]
        }, "/user")

        resource_ds = kc_client.create_resource({
            "name": f"{self.id}-{self.name}",
            "displayName": f"{self.id} - {self.name}",
            "scopes": admin_ds_scope,
            "uris": []
        })
        kc_client.create_permission({
            "name": f"{self.id}-{self.name} Admin Permission",
            "description": "List of policies that will allow certain users or roles to administrate the dataset",
            "type": "resource",
            "logic": "POSITIVE",
            "decisionStrategy": "AFFIRMATIVE",
            "policies": [admin_policy["id"], sys_policy["id"], policy["id"]],
            "resources": [resource_ds["_id"]],
            "scopes": [scope["id"] for scope in admin_ds_scope]
        })

    def update(self, **kwargs):
        """
        Updates the instance with new values. These should be
        already validated.
        """
        # Both of these compare kwargs against the current values - the secret's name
        # and the Keycloak resource name are derived from them - so they run before the
        # UPDATE, while self still holds the old ones.
        self.update_kubernetes_secret(**kwargs)
        self.update_keycloak(**kwargs)

        # Query.update() takes a dict of column -> value. username and password are
        # not columns and were handled above.
        values = {k: v for k, v in kwargs.items() if k in self._get_fields_name()}
        if values:
            self.query.filter(Dataset.id == self.id).update(
                values, synchronize_session='evaluate'
            )

    def update_kubernetes_secret(self, **kwargs):
        if not kwargs:
            return

        v1 = KubernetesClient()
        new_username = kwargs.pop("username", None)
        secret_name: str = self.get_creds_secret_name()

        # Get existing secret
        from typing import cast
        secret: V1Secret = cast(
            V1Secret,
            v1.read_namespaced_secret(secret_name, DEFAULT_NAMESPACE)
        )

        # Update secret if credentials are provided. The keys have to be the ones
        # create_kubernetes_secret wrote, which are also the ones get_credentials, the
        # task pod env and the Dagster pipes op read - anything else updates a key
        # nobody looks at and leaves the old credentials in service.
        new_name = kwargs.get("name", None)
        if new_username:
            secret.data["USERNAME"] = KubernetesClient.encode_secret_value(new_username)
        new_pass = kwargs.pop("password", None)
        if new_pass:
            secret.data["PASSWORD"] = KubernetesClient.encode_secret_value(new_pass)

        secret_task: V1Secret = cast(
            V1Secret,
            v1.read_namespaced_secret(secret_name, TASK_NAMESPACE)
        )

        secret.metadata.labels = {
            "type": "database",
            "host": secret_name
        }
        secret_task.data = secret.data
        # Check secret names
        new_host = kwargs.get("host", None)
        try:
            # Create new secret if name is different
            if (new_host != self.host and new_host) or (new_name != self.name and new_name):
                secret.metadata.name = self.get_creds_secret_name(new_host, new_name)
                secret_task.metadata = secret.metadata
                secret.metadata.resource_version = None
                v1.create_namespaced_secret(DEFAULT_NAMESPACE, body=secret, pretty='true')
                v1.create_namespaced_secret(TASK_NAMESPACE, body=secret_task, pretty='true')
                v1.delete_namespaced_secret(namespace=DEFAULT_NAMESPACE, name=secret_name)
                v1.delete_namespaced_secret(namespace=TASK_NAMESPACE, name=secret_name)
            else:
                v1.patch_namespaced_secret(namespace=DEFAULT_NAMESPACE, name=secret_name, body=secret)
                v1.patch_namespaced_secret(namespace=TASK_NAMESPACE, name=secret_name, body=secret_task)
        except ApiException as e:
            # Host and name are unique so there shouldn't be duplicates. If so
            # let the exception to be re-raised with the internal one
            raise KubernetesException(e.body, 400) from e

    def update_keycloak(self, **kwargs):
        kc_client = Keycloak()
        new_name = kwargs.get("name", None)
        if new_name and new_name != self.name:
            update_args = {
                "name": f"{self.id}-{kwargs['name']}",
                "displayName": f"{self.id} - {kwargs['name']}"
            }
            kc_client.patch_resource(f"{self.id}-{self.name}", **update_args)

    @classmethod
    def get_dataset_by_name_or_id(
        cls,
        id: int | None = None,
        name: str | None = None
    ) -> "Dataset":
        """
        Common function to get a dataset by name or id.
        If both arguments are provided, then tries to find as an AND condition
            rather than an OR.

        Returns:
         Dataset:

        Raises:
            DBRecordNotFoundError: if no record is found
        """
        if id and name:
            error_msg = f"Dataset \"{name}\" with id {id} does not exist"
            dataset = cls.query.filter((Dataset.name.ilike(name or "") & (Dataset.id == id))).one_or_none()
        else:
            error_msg = f"Dataset {name if name else id} does not exist"
            dataset = cls.query.filter((Dataset.name.ilike(name or "") | (Dataset.id == id))).one_or_none()

        if not dataset:
            raise DBRecordNotFoundError(error_msg)

        return dataset

    def _get_secret(self, name) -> V1Secret:
        v1 = KubernetesClient()
        return typing.cast(V1Secret, v1.read_namespaced_secret(name, DEFAULT_NAMESPACE))
