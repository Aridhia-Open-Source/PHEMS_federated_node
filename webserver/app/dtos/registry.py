from app.dtos.base import DTO


class RegistryDTO(DTO):
    id: int
    url: str
    needs_auth: bool | None
    active: bool | None
