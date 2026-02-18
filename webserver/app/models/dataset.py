import logging
import re
from sqlalchemy import Column, Integer, String
from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE
from app.helpers.exceptions import DBRecordNotFoundError, KubernetesException
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from kubernetes.client import V1Secret
from kubernetes.client.exceptions import ApiException

from app.helpers.connection_string import Mssql, Postgres, Mysql, Oracle, MariaDB

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
    schema_read = Column(String(256), nullable=True)
    schema_write = Column(String(256), nullable=True)
    type = Column(String(256), server_default="postgres", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)
    repository = Column(String(4096), nullable=True)

    catalogue = db.relationship("Catalogue", back_populates="dataset", uselist=False, cascade="all, delete-orphan")
    dictionaries = db.relationship("Dictionary", back_populates="dataset", cascade="all, delete-orphan")

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
        return SUPPORTED_ENGINES[self.type](
            user=un,
            passw=passw,
            host=self.host,
            port=self.port,
            database=self.name,
            args=self.extra_connection_args
        ).connection_str

    def get_credentials(self) -> tuple:
        """
        Mostly used to create a direct connection to the DB, i.e. /beacon endpoint
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

    def update(self, **kwargs):
        """
        Updates the instance with new values. These should be
        already validated.
        """
        # Nothing to validate, i.e updating the dictionaries only
        if not kwargs:
            return

        kc_client = Keycloak()
        v1 = KubernetesClient()
        new_username = kwargs.pop("username", None)
        secret_name:str = self.get_creds_secret_name()

        # Get existing secret
        secret: V1Secret = v1.read_namespaced_secret(secret_name, DEFAULT_NAMESPACE, pretty='pretty')
        secret_task: V1Secret = v1.read_namespaced_secret(secret_name, TASK_NAMESPACE, pretty='pretty')

        # Update secret if credentials are provided
        new_name = kwargs.get("name", None)
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
