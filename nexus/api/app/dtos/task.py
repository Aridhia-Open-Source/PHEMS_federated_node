from typing import Self

from app.dtos.base import DTO, WireDatetime
from app.dtos.dataset import DatasetDTO
from app.dtos.task_spec import TaskSpecRequest
from app.helpers.task_config import build_snapshot, snapshot_hash
from app.models.trigger import Trigger


class TaskSpecDTO(DTO):
    image: str
    dataset_id: int | None
    env: dict


class TaskDTO(DTO):
    id: int
    name: str
    spec: TaskSpecDTO
    attempt: int
    status: str | None
    created_at: WireDatetime
    updated_at: WireDatetime
    requested_by: str
    project_id: int
    trigger_id: int
    executor_run_id: str | None
    exit_code: int | None
    state_cause: str | None
    config_hash: str | None
    started_at: WireDatetime | None
    completed_at: WireDatetime | None


class TaskPageDTO(DTO):
    """The response shape of the task lists, a page of tasks."""
    tasks: list[TaskDTO]
    total: int
    page: int
    per_page: int
    pages: int


class TaskConfigDTO(DTO):
    """Whether the configuration a task was created under still holds, see helpers/task_config.decide_launch."""
    # "launch" or "fail"
    outcome: str
    cause: str | None
    current: bool
    changes: list[str]
    config_hash: str | None
    # The pinned configuration itself, see helpers/task_config.build_snapshot. Null for a task without one
    config_snapshot: dict | None
    revoked: list[str]


class TaskCreatedDTO(DTO):
    """The response of requesting a task: the task, the API request that yielded it and when it was created."""
    id: int
    api_request_id: int
    status: str | None
    # ISO 8601, as the model's isoformat
    created_at: str | None


class TaskLaunchDTO(DTO):
    """
    What the launcher is told for a PENDING task: outcome "launch" with the task and its dataset (null for a
    task without one), or "fail" with the cause, the failed task and no dataset. See tasks_api.launch_task.
    """
    outcome: str
    cause: str | None
    task: TaskDTO
    dataset: DatasetDTO | None


class NewTaskDTO(DTO):
    """
    The columns of a Task that has yet to be created.
    """
    name: str
    requested_by: str
    project_id: int
    trigger_id: int
    params: dict
    # The configuration it is pinned to
    config_snapshot: dict
    config_hash: str
    # The columns of its TaskSpec
    spec: dict

    @classmethod
    def from_spec(cls, spec: TaskSpecRequest, trigger: Trigger) -> Self:
        """
        The one place a Task's columns are derived from a validated spec and its trigger.
        """
        dataset = trigger.project.resolve_dataset(spec.dataset)
        snapshot = build_snapshot(trigger.project, dataset)
        return cls(
            # A pull request spec has no name of its own
            name=spec.name or trigger.title,
            requested_by=trigger.requested_by,
            project_id=trigger.project_id,
            trigger_id=trigger.id,
            params=spec.params,
            config_snapshot=snapshot,
            config_hash=snapshot_hash(snapshot),
            spec={"image": spec.image, "dataset_id": dataset.id if dataset else None, "env": spec.env},
        )
