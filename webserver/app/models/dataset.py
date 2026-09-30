import logging
import re
import typing
import urllib.parse

import sqlalchemy as sa
from sqlalchemy.orm import relationship
from kubernetes.client import V1Secret

from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE, PUBLIC_URL
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from app.models import Models, sqla_column

logger = logging.getLogger("dataset_model")
logger.setLevel(logging.INFO)

SUPPORTED_ENGINES = ("mssql", "postgres", "mysql", "oracle", "mariadb")


class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    # The secret holding the database credentials (USERNAME and PASSWORD). The composite
    # foreign key below keeps it to a secret of this dataset's own project.
    k8s_secret_id = sa.Column(sa.Integer, nullable=False)

    name = sa.Column(sa.String(256), unique=True, nullable=False)
    host = sa.Column(sa.String(256), nullable=False)
    port = sa.Column(sa.Integer, default=5432)
    read_schema = sa.Column(sa.String(256), nullable=True)
    write_schema = sa.Column(sa.String(256), nullable=True)
    type = sa.Column(sa.String(256), server_default="postgres", nullable=False)
    extra_connection_args = sa.Column(sa.String(4096), nullable=True)

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ['project_id', 'k8s_secret_id'], ['k8s_secrets.project_id', 'k8s_secrets.id'],
            ondelete='RESTRICT'
        ),
    )

    project = relationship(
        "Project", back_populates="datasets", foreign_keys=[project_id]
    )
    k8s_secret = relationship("K8sSecret", back_populates="datasets", overlaps="project")

    def __init__(
        self,
        name: str,
        host: str,
        k8s_secret_id: int,
        port: int = 5432,
        read_schema: str | None = None,
        write_schema: str | None = None,
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
        self.read_schema = read_schema
        self.write_schema = write_schema
        self.type = type
        self.k8s_secret_id = k8s_secret_id
        self.extra_connection_args = extra_connection_args
        self.project_id = project_id

        if self.type.lower() not in SUPPORTED_ENGINES:
            raise InvalidRequest(f"DB type {self.type} is not supported.")

    def __repr__(self):
        return f'<Dataset {self.name}>'

    @property
    def k8s_secret_name(self) -> str:
        return self.k8s_secret.name

    @property
    def k8s_secret_k8s_name(self) -> str:
        return self.k8s_secret.k8s_name

    def add(self, commit=True, user_id=None):
        super().add(commit)
        # First dataset into a project becomes what a task gets when it names only the
        # project. Later ones do not displace it.
        project = Models.Project.get_by_id(self.project_id)
        if project.default_dataset_id is None:
            project.default_dataset_id = self.id
            project.add(commit)
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
        secret = self._get_secret(self.k8s_secret_k8s_name)
        if secret.data is None:
            raise ValueError("Secret data is None")

        user = KubernetesClient.decode_secret_value(secret.data['USERNAME'])
        password = KubernetesClient.decode_secret_value(secret.data['PASSWORD'])

        return user, password

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
        # The Keycloak resource name is derived from the dataset's name, so this runs
        # before the UPDATE, while self still holds the old one.
        self.update_keycloak(**kwargs)

        # Query.update() takes a dict of column -> value
        values = {k: v for k, v in kwargs.items() if k in self._get_fields_name()}
        if values:
            self.query.filter(Dataset.id == self.id).update(
                values, synchronize_session='evaluate'
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
