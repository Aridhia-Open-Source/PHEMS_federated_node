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
