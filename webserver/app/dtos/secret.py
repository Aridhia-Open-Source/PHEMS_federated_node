from app.dtos.base import DTO, WireDatetime
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType


class SecretDTO(DTO):
    id: int
    project_id: int
    label: str
    description: str | None
    provider: SecretProviderType
    key: str
    created_at: WireDatetime
    updated_at: WireDatetime
