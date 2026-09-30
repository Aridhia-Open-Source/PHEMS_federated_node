from app.dtos.base import DTO


class WhitelistedImageDTO(DTO):
    id: int
    registry_id: int | None
    project_id: int
    name: str
    tag: str | None
    sha: str | None
