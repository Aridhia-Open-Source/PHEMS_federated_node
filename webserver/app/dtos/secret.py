from app.dtos.base import DTO, WireDatetime
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType


class SecretRefDTO(DTO):
    label: str
    provider: SecretProviderType
    key: str

    @classmethod
    def from_model(cls, obj: Secret):
        return cls(label=obj.label, provider=obj.provider, key=obj.key)


class SecretDTO(DTO):
    id: int
    project_id: int
    label: str
    description: str | None
    provider: SecretProviderType
    key: str
    created_at: WireDatetime
    updated_at: WireDatetime
