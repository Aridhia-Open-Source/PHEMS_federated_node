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
