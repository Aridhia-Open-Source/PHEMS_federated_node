from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.dtos.base import DTO, WireDatetime
from app.dtos.user import UserRefDTO
from app.helpers.exceptions import InvalidRequest
from app.models.git_provider import GitProvider
from app.models.git_provider_type import GitProviderType


class GitProviderRefDTO(DTO):
    """A git provider as nested in a repository."""
    id: int
    name: str
    type: GitProviderType
    uri: str
    api_uri: str
    enabled: bool
    revoked: bool


class GitProviderDTO(GitProviderRefDTO):
    # The nexus operator's user when its custom resource declares the record (ADR 0032)
    managed_by: str | None
    created_at: WireDatetime
    updated_at: WireDatetime
    owner: UserRefDTO | None
    # The group whose members alone may change it, null when it is open (ADR 0036)
    owner_group: str | None

    @classmethod
    def from_model(cls, obj: GitProvider):
        return cls.model_validate(obj)


class GitProviderRequest(BaseModel):
    """A git provider in a create request."""
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=253)
    type: str = Field(min_length=1)
    uri: str = Field(min_length=1, max_length=4096)
    api_uri: str = Field(min_length=1, max_length=4096)
    enabled: bool = True

    @classmethod
    def parse(cls, body) -> "GitProviderRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid git provider: {ve}") from ve


class GitProviderPatchRequest(BaseModel):
    """The fields of a git provider that can be updated, all optional but never null."""
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=253)
    type: str | None = Field(default=None, min_length=1)
    uri: str | None = Field(default=None, min_length=1, max_length=4096)
    api_uri: str | None = Field(default=None, min_length=1, max_length=4096)
    enabled: bool | None = None
    revoked: bool | None = None

    @model_validator(mode="after")
    def not_null(self):
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self

    @classmethod
    def parse(cls, body) -> "GitProviderPatchRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid git provider update: {ve}") from ve
