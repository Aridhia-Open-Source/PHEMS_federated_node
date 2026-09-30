from app.dtos.base import DTO, WireDatetime


class RequestDTO(DTO):
    id: int
    dataset_id: int | None
    project_id: int | None
    title: str
    description: str | None
    requested_by: str
    project_name: str
    status: str | None
    proj_start: WireDatetime
    proj_end: WireDatetime
    created_at: WireDatetime
    updated_at: WireDatetime
