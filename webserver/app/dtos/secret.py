from app.dtos.base import DTO, WireDatetime
from app.models.secret import Secret
from app.models.secret_provider import SecretProvider


class SecretRefDTO(DTO):
    name: str
    provider: SecretProvider
    key: str

    @classmethod
    def from_model(cls, obj: Secret):
        return cls(name=obj.name, provider=obj.provider, key=obj.key)


class SecretDTO(DTO):
    id: int
    project_id: int
    name: str
    provider: SecretProvider
    key: str
    created_at: WireDatetime
    updated_at: WireDatetime
