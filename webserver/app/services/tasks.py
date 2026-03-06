from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.container import Container
from app.models.task import Task
from app.schemas.tasks import TaskCreate
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import Keycloak
from app.models.request import RequestModel


class TaskService:
    @staticmethod
    def add(session: Session, data: TaskCreate, dry_run:bool = False) -> Task:
        kc_client = Keycloak()
        user_token = Keycloak.get_token_from_headers()

        user = kc_client.get_user_by_id(data.requested_by)
        task_definition: dict[str, Any] = data.model_dump()
        if data.repository:
            ds: Dataset | None = session.execute(
                select(Dataset).where(Dataset.repository.ilike(data.repository))
            ).scalars().one_or_none()
            if ds is None:
                raise InvalidRequest(f"No datasets linked with the repository {data.repository}")

            task_definition["dataset_id"] = ds.id

        elif kc_client.is_user_admin(user_token):
            ds_id = data.tags.get("dataset_id")
            ds_name = data.tags.get("dataset_name")
            if ds_name or ds_id:
                task_definition["dataset"] = Dataset.get_dataset_by_name_or_id(session, name=ds_name, id=ds_id)
            else:
                raise InvalidRequest("Administrators need to provide `tags.dataset_id` or `tags.dataset_name`")
        else:
            task_definition["dataset"] = RequestModel.get_active_project(
                session,
                data["project_name"],
                user["id"]
            ).dataset

        image: str | Container = Task.get_image_with_repo(session, data.docker_image, string_only=False)
        task_definition["docker_image"] = image.full_image_name()
        task_definition["regcred_secret"] = image.registry.slugify_name()
        task = Task(**task_definition)
        if not dry_run:
            task.add(session)
        return task
