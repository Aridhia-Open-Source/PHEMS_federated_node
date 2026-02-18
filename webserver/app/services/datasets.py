from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from app.models.dataset import Dataset
from app.schemas.datasets import DatasetCreate
from app.helpers.keycloak import Keycloak
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary


class DatasetService:
    @staticmethod
    def add(data: DatasetCreate, user_id: str):
        dataset_data = data.model_dump(exclude={'catalogue', 'dictionaries'})
        user_db = dataset_data.pop("username")
        passw = dataset_data.pop("password")
        dataset = Dataset(**dataset_data)
        if data.catalogue:
          dataset.catalogue = Catalogue(**data.catalogue.model_dump())

        # 3. Attach Dictionaries (SQLA maps dataset_id for every item in list)
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
