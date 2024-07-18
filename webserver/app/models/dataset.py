import os
import re
from sqlalchemy import Column, Integer, String
from app.helpers.db import BaseModel, db
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesClient

TASK_NAMESPACE = os.getenv("TASK_NAMESPACE")

class Dataset(db.Model, BaseModel):
    __tablename__ = 'datasets'
    # No duplicated name/host entries
    # __table_args__ = (
    #     UniqueConstraint('name', 'host'),
    # )
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, default=5432)

    def __init__(self, name:str, host:str, username:str, password:str, port:int=5432):
        self.name = name
        self.host = host
        self.port = port

        v1 = KubernetesClient()
        v1.create_secret(
            name=self.get_creds_secret_name(),
            data={
                "PGPASSWORD":password,
                "PGUSER": username
            },
            namespaces=["default", TASK_NAMESPACE]
        )

    def get_creds_secret_name(self):
        cleaned_up_host = re.sub('http(s)*://', '', self.host)
        return f"{cleaned_up_host}-{self.name.lower().replace(' ', '-')}-creds"

    def get_credentials(self) -> tuple:
        v1 = KubernetesClient()
        secret = v1.get_secret(self.get_creds_secret_name())
        return secret['PGUSER'], secret['PGPASSWORD']

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
