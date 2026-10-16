import logging
import re
import time
import typing
import urllib.parse
from collections.abc import Callable

import pymssql
import sqlalchemy as sa
from kubernetes.client import V1Secret
from kubernetes.client.exceptions import ApiException
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import relationship
from sqlalchemy.pool import NullPool

from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, PUBLIC_URL, build_sql_uri
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from app.models import sqla_column
from app.models.git_provider import ConnectionCheck, ConnectionStatus

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)

SUPPORTED_ENGINES = ("mssql", "postgres", "mysql", "oracle", "mariadb")
CONNECTION_TIMEOUT = 5
MAX_MESSAGE_LENGTH = 200


class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    # The secret holding the database credentials (USERNAME and PASSWORD).
    secret_id = sa.Column(
        sa.Integer, sa.ForeignKey('secrets.id', ondelete='RESTRICT'), nullable=False
    )

    name = sa.Column(sa.String(256), unique=True, nullable=False)
    host = sa.Column(sa.String(256), nullable=False)
    port = sa.Column(sa.Integer, nullable=False)
    read_schema = sa.Column(sa.String(256), nullable=True)
    write_schema = sa.Column(sa.String(256), nullable=True)
    type = sa.Column(sa.String(256), server_default="postgres", nullable=False)
    extra_connection_args = sa.Column(sa.String(4096), nullable=True)
    # Turned on or off for the whole node, whatever the projects' links say
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    # The keys the dataset's secret holds
    SECRET_KEYS = ("USERNAME", "PASSWORD")

    project_assignments = relationship("ProjectDataset", back_populates="dataset")
    secret = relationship("Secret", back_populates="datasets")

    def __init__(
        self,
        name: str,
        host: str,
        secret_id: int,
        port: int,
        read_schema: str | None = None,
        write_schema: str | None = None,
        type: str = "postgres",
        extra_connection_args: str | None = None,
        enabled: bool = True,
        **kwargs
    ):
        self.name = urllib.parse.unquote(name).lower()
        self.slug = self.slugify_name()
        self.url = f"https://{PUBLIC_URL}/datasets/{self.slug}"
        self.host = host
        self.port = port
        self.read_schema = read_schema
        self.write_schema = write_schema
        self.type = type
        self.secret_id = secret_id
        self.extra_connection_args = extra_connection_args
        self.enabled = enabled

        if self.type.lower() not in SUPPORTED_ENGINES:
            raise InvalidRequest(f"DB type {self.type} is not supported.")

    def __repr__(self):
        return f'<Dataset {self.name}>'

    def add(self, commit=True, user_id=None):
        super().add(commit)
        # TODO: Keycloak registration for datasets is detached for now. Re-attach
        # self.add_to_keycloak(user_id) when the Keycloak/authorization rework lands.
        return self

    @classmethod
    def validate(cls, data: dict) -> dict:
        data = dict(data)  # prevent mutation
        return super().validate(data)

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
        secret = self._get_secret(self.secret.key)
        if secret.data is None:
            raise ValueError("Secret data is None")

        user = KubernetesClient.decode_secret_value(secret.data['USERNAME'])
        password = KubernetesClient.decode_secret_value(secret.data['PASSWORD'])

        return user, password

    def prepare_connection_check(self) -> Callable[[], ConnectionCheck]:
        """
        Whether the node can connect to the dataset's database with its secret: opens a
        connection and runs SELECT 1. Only postgres and mssql datasets can be checked.
        Nothing returned includes the credentials.

        Reads the credentials (the database and the cluster) now, and returns the network
        call to make later, which touches neither so it can run in a thread.
        """
        try:
            user, password = self.get_credentials()
        except (KeyError, ValueError):
            check = ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {self.secret.label} has no USERNAME or PASSWORD"
            )
            return lambda: check
        except ApiException as e:
            if e.status != 404:
                raise
            check = ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {self.secret.label} not found"
            )
            return lambda: check

        host = re.sub('http(s)*://', '', self.host)
        return lambda: self._connection_check(self.type, host, self.port, self.name, user, password)

    @staticmethod
    def _connection_check(engine_type: str, host: str, port: int, database: str, user: str, password: str) -> ConnectionCheck:
        started = time.perf_counter()
        try:
            if engine_type == "postgres":
                engine = sa.create_engine(
                    build_sql_uri(host=host, port=port, username=user, password=password, database=database),
                    poolclass=NullPool,
                    connect_args={"connect_timeout": CONNECTION_TIMEOUT},
                )
                with engine.connect() as connection:
                    connection.execute(sa.text("SELECT 1"))
            elif engine_type == "mssql":
                with pymssql.connect(
                    host=host, user=user, password=password, database=database, port=port,
                    login_timeout=CONNECTION_TIMEOUT, timeout=CONNECTION_TIMEOUT
                ) as connection:
                    cursor = connection.cursor()
                    cursor.execute("SELECT 1")
            else:
                return ConnectionCheck(ConnectionStatus.ERROR, f"{engine_type} datasets cannot be checked")
        except (OperationalError, pymssql.OperationalError) as e:
            return ConnectionCheck(
                ConnectionStatus.UNREACHABLE, Dataset._message_of(e),
                latency_ms=round((time.perf_counter() - started) * 1000)
            )
        except (SQLAlchemyError, pymssql.Error) as e:
            return ConnectionCheck(
                ConnectionStatus.ERROR, Dataset._message_of(e),
                latency_ms=round((time.perf_counter() - started) * 1000)
            )
        return ConnectionCheck(
            ConnectionStatus.OK, "OK", latency_ms=round((time.perf_counter() - started) * 1000)
        )

    @staticmethod
    def _message_of(error: Exception) -> str:
        """The driver's first line ("password authentication failed for user ..."), which has no password."""
        return str(getattr(error, "orig", error)).strip().splitlines()[0][:MAX_MESSAGE_LENGTH]

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
        # TODO: Keycloak resource renaming is detached for now. Re-attach
        # self.update_keycloak(**kwargs) (before the UPDATE, while self still holds
        # the old name) when the Keycloak/authorization rework lands.

        # Query.update() takes a dict of column -> value
        values = {k: v for k, v in kwargs.items() if k in self._get_fields_name()}
        if values:
            self.query.filter(Dataset.id == self.id).update(
                values, synchronize_session='evaluate'
            )

    def remove_from_keycloak(self):
        """
        Delete what add_to_keycloak creates: the resource, its admin permission
        and its admin policy.
        """
        # TODO: delete the resource f"{self.id}-{self.name}", the permission
        # f"{self.id}-{self.name} Admin Permission" and the policy
        # f"{self.id} - {self.name} Admin Policy"
        raise NotImplementedError(
            "TODO: delete the dataset's Keycloak resource, permission and policy"
        )

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
