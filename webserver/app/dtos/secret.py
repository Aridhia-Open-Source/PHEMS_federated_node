from app.dtos.base import DTO, WireDatetime
from app.models.secret_type import SecretType


class SecretDTO(DTO):
    id: int
    project_id: int
    name: str
    secret_type: SecretType
    store_name: str
    created_at: WireDatetime
    updated_at: WireDatetime
