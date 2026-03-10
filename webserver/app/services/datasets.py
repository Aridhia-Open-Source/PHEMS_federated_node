from typing import List
from kubernetes.client import V1Secret
from kubernetes.client.exceptions import ApiException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.helpers.const import DEFAULT_NAMESPACE, TASK_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from app.models.dataset import Dataset
from app.schemas.datasets import DatasetCreate, DatasetUpdate
from app.helpers.keycloak import Keycloak
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from app.helpers.exceptions import InvalidRequest, KubernetesException


class DatasetService:
    @staticmethod
    async def add(session: AsyncSession, data: DatasetCreate) -> Dataset:
        if await Dataset.get_dataset_by_name_or_id(session=session, name=data.name, raise_if_not_found=False):
            raise InvalidRequest("Dataset already exist with that name")

        if data.repository:
            existing_link = (await session.execute(
                select(Dataset).filter(Dataset.repository == data.repository)
            )).one_or_none()
            if existing_link:
                raise InvalidRequest(
                    "Repository is already linked to another dataset. Please PATCH that dataset with repository: null"
                )

        kc_client = Keycloak()
        token_info = kc_client.decode_token(kc_client.get_token_from_headers())
        user_id = kc_client.get_user_by_email(token_info["email"])["id"]

        dataset_data = data.model_dump(exclude={'catalogue', 'dictionaries'})
        dataset = Dataset(**dataset_data)

        if data.catalogue:
            dataset.catalogue = Catalogue(**data.catalogue.model_dump())

        if data.dictionaries:
            dataset.dictionaries = [
                Dictionary(**d.model_dump()) for d in data.dictionaries
            ]

        try:
            await dataset.add(session, False)
            v1 = KubernetesClient()
            v1.create_secret(
                name=dataset.get_creds_secret_name(),
                values={
                    "PGPASSWORD": dataset.password,
                    "PGUSER": dataset.username,
                    "MSSQL_PASSWORD": dataset.password,
                    "MSSQL_USER": dataset.username
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
            await session.commit()
            return dataset
        except Exception as e:
            # If the DB commit failed, we haven't touched K8s yet.
            # If K8s fails, we might want to rollback the DB or log a critical error.
            await session.rollback()
            raise e

    @staticmethod
    async def update(session: AsyncSession, ds:Dataset, data: DatasetUpdate) -> Dataset:
        """
        Updates the instance with new values. These should be
        already validated.
        """
        kc_client = Keycloak()
        v1 = KubernetesClient()

        new_name: dict = data.get("name")
        secret_name: str = ds.get_creds_secret_name()

        cata: dict = data.pop("catalogue", None)
        session.add(ds)
        if cata:
            if ds.catalogue and ds.catalogue.title == cata["title"]:
                await session.execute(
                    update(Catalogue).where(Catalogue.title == cata["title"]).values(cata)
                )
            else:
                ds.catalogue = Catalogue(**cata)

        dicts: List[dict] = data.pop("dictionaries", None)
        if dicts:
            # Needs to validate existing dictionaries and update them if
            # necessary or add them
            for d in dicts:
                if not (await session.execute(
                    select(Dictionary).where(Dictionary.dataset_id == ds.id).filter_by(**d)
                )).all():
                    q = select(Dictionary).filter_by(
                        dataset_id=ds.id,
                        field_name=d["field_name"],
                        table_name=d["table_name"]
                    )
                    if (await session.execute(q)).all():
                        update(Dictionary).filter_by(
                            dataset_id=ds.id,
                            field_name=d["field_name"],
                            table_name=d["table_name"]
                        ).values(d)
                    else:
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
            existing_link = await session.execute(
                select(Dataset).filter(Dataset.repository == data["repository"], Dataset.id != ds.id)
            ).one_or_none()
            if existing_link:
                raise InvalidRequest(
                    "Repository is already linked to another dataset. Please PATCH that dataset with repository: null"
                )
        # Update table
        if data:
            await ds.update(session, data)

        return ds
