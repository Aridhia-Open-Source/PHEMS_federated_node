from app.dtos.base import DTO, WireDatetime
from app.models.project_secret import ProjectSecret
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType


class SecretDTO(DTO):
    id: int
    label: str
    description: str | None
    provider: SecretProviderType
    key: str
    namespace: str | None
    enabled: bool
    created_at: WireDatetime
    updated_at: WireDatetime


class ProjectSecretDTO(DTO):
    """A project's resource for a global secret, the reference nested. Addressed by the secret's label. Never carries values."""
    project_id: int
    secret: SecretDTO
    enabled: bool
    revoked: bool
    active: bool

    @classmethod
    def from_model(cls, obj: ProjectSecret):
        return cls(
            project_id=obj.project_id,
            secret=SecretDTO.from_model(obj.secret),
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
        )
