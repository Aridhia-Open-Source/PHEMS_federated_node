import logging
import re
import requests
from sqlalchemy import Column, Integer, String
from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE, PUBLIC_URL, DATASET_MOUNT_PATH
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, KubernetesException
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from kubernetes.client import V1PersistentVolumeClaim, V1Secret
from kubernetes.client.exceptions import ApiException

from app.helpers.connection_string import Mssql, Postgres, Mysql, Oracle, MariaDB, DuckDB, Sqlite

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)

SERVER_ENGINES = {
    "mssql": Mssql,
    "postgres": Postgres,
    "mysql": Mysql,
    "oracle": Oracle,
    "mariadb": MariaDB
}
# Embedded engines, read from a file on a PVC mounted into the task pod
FILE_ENGINES = {
    "duckdb": DuckDB,
    "sqlite": Sqlite
}
SUPPORTED_ENGINES = {**SERVER_ENGINES, **FILE_ENGINES}

class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    host = Column(String(256), nullable=True)
    port = Column(Integer, nullable=True)
    schema = Column(String(256), nullable=True)
    schema_write = Column(String(256), nullable=True)
    type = Column(String(256), server_default="postgres", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)
    repository = Column(String(4096), nullable=True)
    volume_claim = Column(String(256), nullable=True)
    path = Column(String(1024), nullable=True)

    def __init__(self,
                 name:str,
                 host:str=None,
                 username:str=None,
                 password:str=None,
                 port:int=None,
                 schema:str=None,
                 schema_write:str=None,
                 type:str="postgres",
                 extra_connection_args:str=None,
                 repository:str=None,
                 volume_claim:str=None,
                 path:str=None,
                 **kwargs
                ):
        self.name = requests.utils.unquote(name).lower()
        self.slug = self.slugify_name()
        self.url = f"https://{PUBLIC_URL}/datasets/{self.slug}"
        self.type = type
        self.validate_connection_fields({
            "type": type, "host": host, "port": port, "username": username,
            "password": password, "schema_write": schema_write,
            "volume_claim": volume_claim, "path": path
        }, creating=True)

        self.host = host
        self.port = port
        self.schema = schema
        self.schema_write = schema_write
        self.username = username
        self.password = password
        self.extra_connection_args = extra_connection_args
        self.volume_claim = volume_claim
        self.path = path
        if self.is_file_based:
            self.schema = schema or "main"
        else:
            self.port = port or 5432
        if repository:
            self.repository = repository.lower()

    @property
    def is_file_based(self) -> bool:
        return (self.type or "").lower() in FILE_ENGINES

    @classmethod
    def validate_connection_fields(cls, fields:dict, creating:bool=False):
        """
        Checks the combination of connection related fields. Server engines
        need a host and credentials, file engines need a volume claim and a path.
        `fields` is the full set of values the dataset would end up with.
        When updating, credentials are already stored, so they're not required.
        """
        ds_type = (fields.get("type") or "").lower()
        if ds_type not in SUPPORTED_ENGINES:
            raise InvalidRequest(f"DB type {fields.get('type')} is not supported.")

        def not_allowed(keys:list):
            provided = [k for k in keys if fields.get(k) is not None]
            if provided:
                raise InvalidRequest(f"{', '.join(provided)} not allowed for {ds_type} datasets")

        if ds_type in SERVER_ENGINES:
            not_allowed(["volume_claim", "path"])
            if not fields.get("host"):
                raise InvalidRequest("host is required")
            if creating and not (fields.get("username") and fields.get("password")):
                raise InvalidRequest("username and password are required")
            return

        # The file is read-only and on a volume, there's no server to log in to
        not_allowed(["host", "port", "username", "password", "schema_write"])
        if not fields.get("volume_claim"):
            raise InvalidRequest("volume_claim is required")
        path = fields.get("path")
        if not path:
            raise InvalidRequest("path is required")
        if path.startswith("/") or ".." in path.split("/"):
            raise InvalidRequest("path must be relative and can't contain '..'")

    def dataset_path(self) -> str:
        """
        Where the file is found inside the task pod
        """
        return f"{DATASET_MOUNT_PATH}/{self.path}"

    def get_volume_claim(self) -> V1PersistentVolumeClaim:
        """
        Fetches the PVC the file lives on, so a missing one is reported
        when the task is requested, rather than leaving the pod Pending
        """
        try:
            return KubernetesClient().read_namespaced_persistent_volume_claim(
                self.volume_claim, TASK_NAMESPACE
            )
        except ApiException as apie:
            if apie.status == 404:
                raise InvalidRequest(
                    f"Volume claim {self.volume_claim} for dataset {self.name} not found"
                ) from apie
            raise


    @classmethod
    def validate(cls, data:dict) -> dict:
        if data.get("repository"):
            existing_link = cls.query.filter(Dataset.repository == data.get("repository")).one_or_none()
            if existing_link:
                raise InvalidRequest(
                    "Repository is already linked to another dataset. Please PATCH that dataset with repository: null"
                )
        return super().validate(data)

    def get_creds_secret_name(self, host=None, name=None):
        host = host or self.host
        name = name or self.name
        cleaned_up_name = re.sub('\\s|_|#', '-', name.lower())

        # File based datasets have no host
        if not host:
            return f"{cleaned_up_name}-file-creds"
        cleaned_up_host = re.sub('http(s)*://', '', host)
        return f"{cleaned_up_host}-{cleaned_up_name}-creds"

    def get_connection_string(self):
        """
        From the helper classes, return the correct connection string
        """
        if self.is_file_based:
            return FILE_ENGINES[self.type.lower()](
                path=self.dataset_path(),
                args=self.extra_connection_args
            ).connection_str

        un, passw = self.get_credentials()
        return SUPPORTED_ENGINES[self.type](
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
        dataset["url"] = f"https://{PUBLIC_URL}/datasets/{dataset["slug"]}"
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
        v1 = KubernetesClient()
        secret:V1Secret = v1.read_namespaced_secret(
            self.get_creds_secret_name(), DEFAULT_NAMESPACE, pretty='pretty'
        )
        # Doesn't matter which key it's being picked up, the value it's the same
        # in terms of *USER or *PASSWORD
        user = KubernetesClient.decode_secret_value(secret.data['PGUSER'])
        password = KubernetesClient.decode_secret_value(secret.data['PGPASSWORD'])

        return user, password

    def add(self, commit=True, user_id=None):
        super().add(commit)
        # create secrets
        # File based datasets have no credentials to keep
        if not self.is_file_based:
            v1 = KubernetesClient()
            v1.create_secret(
                name=self.get_creds_secret_name(),
                values={
                    "PGPASSWORD": self.password,
                    "PGUSER": self.username,
                    "MSSQL_PASSWORD": self.password,
                    "MSSQL_USER": self.username
                },
                namespaces=[DEFAULT_NAMESPACE, TASK_NAMESPACE]
            )
        delattr(self, "username")
        delattr(self, "password")
        # Add to keycloak
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
        # Nothing to validate, i.e updating the dictionaries only
        if not kwargs:
            return

        self.validate_update(kwargs)

        kc_client = Keycloak()
        new_name = kwargs.get("name", None)
        if self.is_file_based:
            # Nothing is kept in a secret for file based datasets
            self.update_keycloak_and_table(kc_client, new_name, kwargs)
            return

        v1 = KubernetesClient()
        new_username = kwargs.pop("username", None)
        secret_name:str = self.get_creds_secret_name()

        # Get existing secret
        secret: V1Secret = v1.read_namespaced_secret(secret_name, DEFAULT_NAMESPACE, pretty='pretty')
        secret_task: V1Secret = v1.read_namespaced_secret(secret_name, TASK_NAMESPACE, pretty='pretty')

        # Update secret if credentials are provided
        if new_username:
            secret.data["PGUSER"] = KubernetesClient.encode_secret_value(new_username)
        new_pass = kwargs.pop("password", None)
        if new_pass:
            secret.data["PGPASSWORD"] = KubernetesClient.encode_secret_value(new_pass)

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

        self.update_keycloak_and_table(kc_client, new_name, kwargs)

    def validate_update(self, kwargs:dict):
        """
        Checks the dataset would still be valid after the update. Moving
        between file based and server engines needs a new dataset instead.
        """
        new_type = kwargs.get("type") or self.type
        if (new_type.lower() in FILE_ENGINES) != self.is_file_based:
            raise InvalidRequest("type can't change between file based and server engines")

        fields = {
            k: getattr(self, k) for k in [
                "type", "host", "port", "schema_write", "volume_claim", "path"
            ]
        }
        fields.update(kwargs)
        self.validate_connection_fields(fields)

    def update_keycloak_and_table(self, kc_client:Keycloak, new_name:str, kwargs:dict):
        """
        Final part of the update, once the secrets are sorted
        """
        # Check resource names on KC and update them
        if new_name and new_name != self.name:
            update_args = {
                "name": f"{self.id}-{kwargs["name"]}",
                "displayName": f"{self.id} - {kwargs["name"]}"
            }
            kc_client.patch_resource(f"{self.id}-{self.name}", **update_args)

        if kwargs.get("repository"):
            kwargs["repository"] = kwargs.get("repository").lower()
        # Update table
        if kwargs:
            self.query.filter(Dataset.id == self.id).update(kwargs, synchronize_session='evaluate')

    @classmethod
    def get_dataset_by_name_or_id(cls, id:int=None, name:str="") -> "Dataset":
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

    def __repr__(self):
        return f'<Dataset {self.name}>'
