import os
import re
from sqlalchemy import Column, Integer, String
from app.helpers.db import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient
from kubernetes import client
from kubernetes.client.exceptions import ApiException


TASK_NAMESPACE = os.getenv("TASK_NAMESPACE")
SUPPORTED_TYPES = ["postgres", "mssql"]

class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, default=5432)
    type = Column(String(256), server_default="postgres", nullable=False)
    extra_connection_args = Column(String(4096), nullable=True)

    def __init__(self,
                 name:str,
                 host:str,
                 username:str,
                 password:str,
                 port:int=5432,
                 type:str="postgres",
                 extra_connection_args:str=None,
                 **kwargs
                ):
        self.name = name
        self.host = host
        self.port = port
        self.type = type
        self.extra_connection_args = extra_connection_args

        v1 = KubernetesClient()
        body = client.V1Secret()
        body.api_version = 'v1'
        if self.type not in SUPPORTED_TYPES:
            raise InvalidRequest(f"DB type {self.type} is not supported.")

        encoded_psw = KubernetesClient.encode_secret_value(password)
        encoded_un = KubernetesClient.encode_secret_value(username)

        body.data = {
            "PGPASSWORD": encoded_psw,
            "PGUSER": encoded_un,
            "MSSQL_PASSWORD": encoded_psw,
            "MSSQL_USER": encoded_un
        }
        body.kind = 'Secret'
        body.metadata = {'name': self.get_creds_secret_name()}
        body.type = 'Opaque'
        try:
            for ns in ["default", TASK_NAMESPACE]:
                v1.create_namespaced_secret(ns, body=body, pretty='true')
        except ApiException as e:
            if e.status == 409:
                pass
            else:
                raise InvalidRequest(e.reason)

    def get_creds_secret_name(self):
        cleaned_up_host = re.sub('http(s)*://', '', self.host)
        return f"{cleaned_up_host}-{re.sub('\\s|_', '-', self.name.lower())}-creds"

    def get_credentials(self) -> tuple:
        """
        Mostly used to create a direct connection to the DB, i.e. /beacon endpoint
        This is not involved in the Task Execution Service
        """
        v1 = KubernetesClient()
        secret = v1.read_namespaced_secret(self.get_creds_secret_name(), 'default', pretty='pretty')
        # Doesn't matter which key it's being picked up, the value it's the same
        # in terms of *USER or *PASSWORD
        user = KubernetesClient.decode_secret_value(secret.data['PGUSER'])
        password = KubernetesClient.decode_secret_value(secret.data['PGPASSWORD'])

        return user, password

    def add(self, commit=True, user_id=None):
        super().add(commit)
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
            "displayName": f"{self.id}-{self.name}",
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

    def __repr__(self):
        return f'<Dataset {self.name!r}>'
