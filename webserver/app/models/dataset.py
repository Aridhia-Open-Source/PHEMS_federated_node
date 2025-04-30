import logging
import re
import requests
from sqlalchemy import Column, Integer, String
from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE, PUBLIC_URL
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)

SUPPORTED_ENGINES = [
    "mssql",
    "postgres",
    "mysql",
    "oracle",
    "sqlite",
    "mariadb"
]


class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, default=5432)
    schema = Column(String(256), nullable=True)
    type = Column(String(256), server_default="postgres", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)

    def __init__(self,
                 name:str,
                 host:str,
                 username:str,
                 password:str,
                 port:int=5432,
                 schema:str=None,
                 type:str="postgres",
                 extra_connection_args:str=None,
                 **kwargs
                ):
        self.name = requests.utils.unquote(name).lower()
        self.slug = self.slugify_name()
        self.url = f"https://{PUBLIC_URL}/datasets/{self.slug}"
        self.host = host
        self.port = port
        self.schema = schema
        self.type = type
        self.username = username
        self.password = password
        self.extra_connection_args = extra_connection_args

        if self.type.lower() not in SUPPORTED_ENGINES:
            raise InvalidRequest(f"DB type {self.type} is not supported.")

    def get_creds_secret_name(self, host=None, name=None):
        host = host or self.host
        name = name or self.name

        cleaned_up_host = re.sub('http(s)*://', '', host)
        return f"{cleaned_up_host}-{re.sub('\\s|_|#', '-', name.lower())}-creds"

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
        Mostly used to create a direct connection to the DB, i.e. /beacon endpoint
        This is not involved in the Task Execution Service
        """
        v1 = KubernetesClient()
        secret = v1.read_namespaced_secret(self.get_creds_secret_name(), DEFAULT_NAMESPACE, pretty='pretty')
        # Doesn't matter which key it's being picked up, the value it's the same
        # in terms of *USER or *PASSWORD
        user = KubernetesClient.decode_secret_value(secret.data['PGUSER'])
        password = KubernetesClient.decode_secret_value(secret.data['PGPASSWORD'])

        return user, password

    def add(self, commit=True, user_id=None):
        super().add(commit)
        # create secrets
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

        kc_client = Keycloak()
        v1 = KubernetesClient()
        new_username = kwargs.pop("username", None)

        # Get existing secret
        secret = v1.read_namespaced_secret(self.get_creds_secret_name(), DEFAULT_NAMESPACE, pretty='pretty')
        secret_task = v1.read_namespaced_secret(self.get_creds_secret_name(), TASK_NAMESPACE, pretty='pretty')

        # Update secret if credentials are provided
        new_name = kwargs.get("name", None)
        if new_username:
            secret.data["PGUSER"] = KubernetesClient.encode_secret_value(new_username)
        new_pass = kwargs.pop("password", None)
        if new_pass:
            secret.data["PGPASSWORD"] = KubernetesClient.encode_secret_value(new_pass)

        secret_task.data = secret.data
        # Check secret names
        new_host = kwargs.get("host", None)
        try:
            # Create new secret if name is different
            if (new_host != self.host and new_host) or (new_name != self.name and new_name):
                secret.metadata = {'name': self.get_creds_secret_name(new_host, new_name)}
                secret_task.metadata = secret.metadata
                v1.create_namespaced_secret(DEFAULT_NAMESPACE, body=secret, pretty='true')
                v1.create_namespaced_secret(TASK_NAMESPACE, body=secret_task, pretty='true')
                v1.delete_namespaced_secret(namespace=DEFAULT_NAMESPACE, name=self.get_creds_secret_name())
                v1.delete_namespaced_secret(namespace=TASK_NAMESPACE, name=self.get_creds_secret_name())
            else:
                v1.patch_namespaced_secret(namespace=DEFAULT_NAMESPACE, name=self.get_creds_secret_name(), body=secret)
                v1.patch_namespaced_secret(namespace=TASK_NAMESPACE, name=self.get_creds_secret_name(), body=secret_task)
        except ApiException as e:
            logger.error(e.body)
            # Host and name are unique so there shouldn't be duplicates. If so
            # let the exception to be re-raised with the internal one
            raise InvalidRequest(e.reason)

        # Check resource names on KC and update them
        if new_name and new_name != self.name:
            update_args = {
                "name": f"{self.id}-{kwargs["name"]}",
                "displayName": f"{self.id} - {kwargs["name"]}"
            }
            kc_client.patch_resource(f"{self.id}-{self.name}", **update_args)

        # Update table
        if kwargs:
            self.query.filter(Dataset.id == self.id).update(kwargs, synchronize_session='evaluate')

    @classmethod
    def get_dataset_by_name_or_id(cls, id:int=None, name:str="") -> "Dataset":
        """
        Common funcion to get a dataset by name or id.
        If both arguments are provided, then tries to find as an AND condition
            rather than an OR.

        Returns:
         Datset:

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
