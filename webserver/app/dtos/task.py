from typing import Self

from app.dtos.base import DTO, WireDatetime
from app.dtos.task_spec import TaskSpec
from app.models.trigger import Trigger


class TaskDTO(DTO):
    id: int
    name: str
    docker_image: str
    spec: dict
    attempt: int
    status: str | None
    created_at: WireDatetime
    updated_at: WireDatetime
    requested_by: str
    dataset_id: int | None
    project_id: int
    trigger_id: int
    dagster_run_id: str | None
    exit_code: int | None
    started_at: WireDatetime | None
    completed_at: WireDatetime | None


class NewTaskDTO(DTO):
    """
    The columns of a Task that has yet to be created.
    """
    name: str
    docker_image: str
    requested_by: str
    dataset_id: int | None
    project_id: int
    trigger_id: int
    params: dict
    spec: dict

    @classmethod
    def from_spec(cls, spec: TaskSpec, trigger: Trigger) -> Self:
        """
        The one place a Task's columns are derived from a validated spec and its trigger.
        """
        dataset = trigger.project.resolve_dataset(spec.dataset)
        return cls(
            # A pull request spec has no name of its own
            name=spec.name or trigger.title,
            docker_image=spec.image,
            requested_by=trigger.requested_by,
            dataset_id=dataset.id if dataset else None,
            project_id=trigger.project_id,
            trigger_id=trigger.id,
            params=spec.params,
            spec=spec.model_dump(),
        )
