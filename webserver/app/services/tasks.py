from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.task import Task
from app.schemas.tasks import TaskCreate
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import Keycloak
from app.models.request import RequestModel


class TaskService:
    @staticmethod
    async def add(session: AsyncSession, request:Request, data: TaskCreate, dry_run:bool = False) -> Task:
        kc_client = await Keycloak.create()
        user_token = await Keycloak.get_token_from_headers(request)
        decoded_token = await kc_client.decode_token(user_token)

        user = await kc_client.get_user_by_email(decoded_token["email"])
        task_definition: dict[str, Any] = data.model_dump()
        if data.repository:
            ds: Dataset | None = (await session.execute(
                select(Dataset).where(Dataset.repository.ilike(data.repository))
            )).scalars().one_or_none()
            if ds is None:
                raise InvalidRequest(f"No datasets linked with the repository {data.repository}")

            task_definition["dataset_id"] = ds.id

        elif await kc_client.is_user_admin(user_token):
            ds_id = data.tags.get("dataset_id")
            ds_name = data.tags.get("dataset_name")
            if ds_name or ds_id:
                task_definition["dataset"] = await Dataset.get_dataset_by_name_or_id(session, name=ds_name, id=ds_id)
            else:
                raise InvalidRequest("Administrators need to provide `tags.dataset_id` or `tags.dataset_name`")
        else:
            task_definition["dataset"] = await RequestModel.get_active_project(
                session,
                data["project_name"],
                user["id"]
            ).dataset

        image: str | Container = await Task.get_image_with_repo(session, data.docker_image, string_only=False)
        task_definition["docker_image"] = image.full_image_name()
        task_definition["regcred_secret"] = image.registry.slugify_name()
        task_definition["requested_by"] = user["id"]
        task = Task(**task_definition)
        if not dry_run:
            await task.add(session)
        return task
