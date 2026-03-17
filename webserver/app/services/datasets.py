from typing import List
from fastapi import Request
from kubernetes_asyncio.client import V1Secret
from kubernetes_asyncio.client.exceptions import ApiException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.helpers.settings import settings
from app.helpers.kubernetes import KubernetesClient
from app.models.dataset import Dataset
from app.schemas.datasets import DatasetCreate, DatasetUpdate
from app.helpers.keycloak import Keycloak
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from app.helpers.exceptions import InvalidRequest, KubernetesException, LogAndException, DBError


class DatasetService:
    @staticmethod
    async def add(session: AsyncSession, request:Request, data: DatasetCreate) -> Dataset:
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

        kc_client: Keycloak = await Keycloak.create()
        token_info = await kc_client.decode_token(await kc_client.get_token_from_headers(request))
        user_info = await kc_client.get_user_by_email(token_info["email"])
        user_id = user_info["id"]

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
            v1: KubernetesClient = await KubernetesClient.create()
            await v1.create_secret(
                name=dataset.get_creds_secret_name(),
                values={
                    "PGPASSWORD": dataset.password,
                    "PGUSER": dataset.username,
                    "MSSQL_PASSWORD": dataset.password,
                    "MSSQL_USER": dataset.username
                },
                namespaces=[settings.default_namespace, settings.task_namespace]
            )
            # Add to keycloak
            kc_client = await Keycloak.create()
            admin_policy = await kc_client.get_policy('admin-policy')
            sys_policy = await kc_client.get_policy('system-policy')

            admin_ds_scope = []
            admin_ds_scope.append(await kc_client.get_scope('can_admin_dataset'))
            admin_ds_scope.append(await kc_client.get_scope('can_access_dataset'))
            admin_ds_scope.append(await kc_client.get_scope('can_exec_task'))
            admin_ds_scope.append(await kc_client.get_scope('can_admin_task'))
            admin_ds_scope.append(await kc_client.get_scope('can_send_request'))
            admin_ds_scope.append(await kc_client.get_scope('can_admin_request'))
            policy = await kc_client.create_policy({
                "name": f"{dataset.id} - {dataset.name} Admin Policy",
                "description": f"List of users allowed to administrate the {data.name} dataset",
                "logic": "POSITIVE",
                "users": [user_id]
            }, "/user")

            resource_ds = await kc_client.create_resource({
                "name": f"{dataset.id}-{dataset.name}",
                "displayName": f"{dataset.id} - {dataset.name}",
                "scopes": admin_ds_scope,
                "uris": []
            })
            await kc_client.create_permission({
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
            await session.refresh(dataset)
            return dataset
        except LogAndException as lae:
            await session.rollback()
            raise lae
        except IntegrityError as ie:
            await session.rollback()
            raise ie
        except Exception as e:
            # If the DB commit failed, we haven't touched K8s yet.
            # If K8s fails, we might want to rollback the DB or log a critical error.
            await session.rollback()
            raise InvalidRequest("An error occurred during the dataset creation") from e

    @staticmethod
    async def update(session: AsyncSession, ds:Dataset, data: DatasetUpdate) -> Dataset:
        """
        Updates the instance with new values. These should be
        already validated.
        """
        kc_client = await Keycloak.create()
        v1: KubernetesClient = await KubernetesClient.create()

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
        secret: V1Secret = await v1.api_client.read_namespaced_secret(secret_name, settings.default_namespace, pretty='pretty')
        secret_task: V1Secret = await v1.api_client.read_namespaced_secret(secret_name, settings.task_namespace, pretty='pretty')

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
                await v1.api_client.create_namespaced_secret(settings.default_namespace, body=secret, pretty='true')
                await v1.api_client.create_namespaced_secret(settings.task_namespace, body=secret_task, pretty='true')
                await v1.api_client.delete_namespaced_secret(namespace=settings.default_namespace, name=secret_name)
                await v1.api_client.delete_namespaced_secret(namespace=settings.task_namespace, name=secret_name)
            else:
                await v1.api_client.patch_namespaced_secret(namespace=settings.task_namespace, name=secret_name, body=secret_task)
                await v1.api_client.patch_namespaced_secret(namespace=settings.default_namespace, name=secret_name, body=secret)
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
            await kc_client.patch_resource(f"{ds.id}-{ds.name}", **update_args)

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
