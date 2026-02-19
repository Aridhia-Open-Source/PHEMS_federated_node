from typing import List
from kubernetes.client import V1Secret
from kubernetes.client.exceptions import ApiException

from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from app.models.dataset import Dataset
from app.schemas.datasets import DatasetCreate, DatasetUpdate
from app.helpers.keycloak import Keycloak
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from app.helpers.exceptions import KubernetesException


class DatasetService:
    @staticmethod
    def add(data: DatasetCreate, user_id: str):
        dataset_data = data.model_dump(exclude={'catalogue', 'dictionaries'})
        user_db = dataset_data.pop("username")
        passw = dataset_data.pop("password")
        dataset = Dataset(**dataset_data)
        if data.catalogue:
          dataset.catalogue = Catalogue(**data.catalogue.model_dump())

        if data.dictionaries:
            dataset.dictionaries = [
                Dictionary(**d.model_dump()) for d in data.dictionaries
            ]

        try:
          dataset.add(commit=True)

          v1 = KubernetesClient()
          v1.create_secret(
              name=dataset.get_creds_secret_name(),
              values={
                  "PGPASSWORD": passw,
                  "PGUSER": user_db,
                  "MSSQL_PASSWORD": passw,
                  "MSSQL_USER": user_db
              },
              namespaces=[DEFAULT_NAMESPACE, TASK_NAMESPACE]
          )
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
              "name": f"{dataset.id} - {dataset.name} Admin Policy",
              "description": f"List of users allowed to administrate the {data.name} dataset",
              "logic": "POSITIVE",
              "users": [user_id]
          }, "/user")

          resource_ds = kc_client.create_resource({
              "name": f"{dataset.id}-{dataset.name}",
              "displayName": f"{dataset.id} - {dataset.name}",
              "scopes": admin_ds_scope,
              "uris": []
          })
          kc_client.create_permission({
              "name": f"{dataset.id}-{dataset.name} Admin Permission",
              "description": "List of policies that will allow certain users or roles to administrate the dataset",
              "type": "resource",
              "logic": "POSITIVE",
              "decisionStrategy": "AFFIRMATIVE",
              "policies": [admin_policy["id"], sys_policy["id"], policy["id"]],
              "resources": [resource_ds["_id"]],
              "scopes": [scope["id"] for scope in admin_ds_scope]
          })
          return dataset
        except Exception as e:
            # If the DB commit failed, we haven't touched K8s yet.
            # If K8s fails, we might want to rollback the DB or log a critical error.
            db.session.rollback()
            raise e

    @staticmethod
    def update(ds:Dataset, data: DatasetUpdate):
        """
        Updates the instance with new values. These should be
        already validated.
        """
        kc_client = Keycloak()
        v1 = KubernetesClient()

        new_name: dict = data.get("name")
        secret_name: str = ds.get_creds_secret_name()

        cata: dict = data.pop("catalogue", None)
        if cata:
          ds.catalogue = Catalogue(**cata)

        dicts: List[dict] = data.pop("dictionaries", None)
        if dicts:
            # Needs to validate existing dictionaries and update them if
            # necessary or add them
            for d in dicts:
                if not Dictionary.query.filter_by(dataset_id=ds.id, **d).all():
                    ds.dictionaries.append(Dictionary(**d))

        # Get existing secret
        secret: V1Secret = v1.read_namespaced_secret(secret_name, DEFAULT_NAMESPACE, pretty='pretty')
        secret_task: V1Secret = v1.read_namespaced_secret(secret_name, TASK_NAMESPACE, pretty='pretty')

        # Update secret if credentials are provided
        new_username = data.pop("username", None)
        if new_username:
            secret.data["PGUSER"] = KubernetesClient.encode_secret_value(new_username)
        new_pass = data.pop("password", None)
        if new_pass:
            secret.data["PGPASSWORD"] = KubernetesClient.encode_secret_value(new_pass)

        secret.metadata.labels = {
            "type": "database",
            "host": secret_name
        }
        secret_task.data = secret.data
        # Check secret names
        new_host = data.get("host", None)
        try:
            # Create new secret if name is different
            if (new_host != ds.host and new_host) or (new_name != ds.name and new_name):
                secret.metadata.name = ds.get_creds_secret_name(new_host, new_name)
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
        if new_name and new_name != ds.name:
            update_args = {
                "name": f"{ds.id}-{data["name"]}",
                "displayName": f"{ds.id} - {data["name"]}"
            }
            kc_client.patch_resource(f"{ds.id}-{ds.name}", **update_args)

        if data.get("repository"):
            data["repository"] = data.get("repository").lower()
        # Update table
        if data:
            ds.query.update(data, synchronize_session='evaluate')
