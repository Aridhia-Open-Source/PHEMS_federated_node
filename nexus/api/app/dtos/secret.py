from app.dtos.base import DTO, WireDatetime
from app.dtos.user import UserRefDTO
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
    created_by: UserRefDTO | None
    owned_by: UserRefDTO | None


class ProjectSecretDTO(DTO):
    """A project's resource for a global secret, the reference nested. Addressed by the secret's label. Never carries values."""
    project_id: int
    secret: SecretDTO
    enabled: bool
    revoked: bool
    active: bool
    created_by: UserRefDTO | None

    @classmethod
    def from_model(cls, obj: ProjectSecret):
        return cls(
            project_id=obj.project_id,
            secret=SecretDTO.from_model(obj.secret),
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
            created_by=UserRefDTO.of(obj.created_by),
        )
