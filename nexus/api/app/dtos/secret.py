from typing import Annotated

from fednode.clients.kubernetes.names import validate_secret_key
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

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
    owner: UserRefDTO | None
    # The group whose members alone may change it, null when it is open (ADR 0036)
    owner_group: str | None


class ProjectSecretDTO(DTO):
    """A project's resource for a global secret, the reference nested. Addressed by the secret's label. Never carries values."""
    project_id: int
    secret: SecretDTO
    enabled: bool
    revoked: bool
    active: bool
    owner: UserRefDTO | None
    # The group whose members alone may change it, null when it is open (ADR 0036)
    owner_group: str | None

    @classmethod
    def from_model(cls, obj: ProjectSecret):
        return cls(
            project_id=obj.project_id,
            secret=SecretDTO.from_model(obj.secret),
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
            owner=UserRefDTO.of(obj.owner),
            owner_group=obj.owner_group,
        )


def _valid_keys(values: dict[str, str]) -> dict[str, str]:
    for key in values:
        validate_secret_key(key, f"Key {key!r}")
    return values


# At least one key Kubernetes accepts, and a value for each
SecretValues = Annotated[
    dict[str, Annotated[str, Field(min_length=1)]], Field(min_length=1), AfterValidator(_valid_keys)
]


class SecretRequest(BaseModel):
    """A secret in a create request: the values go to the secret store, never to the database."""
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str = Field(min_length=1)
    description: str | None = None
    provider: SecretProviderType = Field(strict=False)
    values: SecretValues
    enabled: bool = True


class SecretPatchRequest(BaseModel):
    """The fields of a secret that can be updated, all optional but never null."""
    model_config = ConfigDict(extra="forbid", strict=True)

    values: SecretValues | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def not_null(self):
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self
