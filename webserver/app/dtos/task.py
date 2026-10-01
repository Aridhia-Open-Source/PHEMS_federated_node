from typing import Self

from app.dtos.base import DTO, WireDatetime


class TaskDTO(DTO):
    id: int
    name: str
    docker_image: str
    status: str | None
    created_at: WireDatetime
    updated_at: WireDatetime
    requested_by: str
    dataset_id: int | None
    project_id: int
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
    task_request_id: int
    api_request_id: int | None
    pr_repository_id: int | None
    pr_number: int | None
    params: dict

    @classmethod
    def from_task_request(cls, task_request) -> Self:
        """
        The one place a Task's columns are derived from its TaskRequest's spec.
        """
        spec = task_request.payload
        pull_request = task_request.pull_request
        dataset = task_request.project.resolve_dataset(spec["dataset"])
        return cls(
            # A pull request spec has no name of its own
            name=spec["name"] or pull_request.title,
            docker_image=spec["image"],
            requested_by=pull_request.raised_by if pull_request else task_request.api_request.user_id,
            dataset_id=dataset.id if dataset else None,
            project_id=task_request.project_id,
            task_request_id=task_request.id,
            api_request_id=task_request.api_request_id,
            pr_repository_id=pull_request.trigger_repository_id if pull_request else None,
            pr_number=pull_request.number if pull_request else None,
            params=spec["params"],
        )
