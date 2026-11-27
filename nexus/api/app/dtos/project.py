from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.dtos.base import DTO, WireDatetime
from app.dtos.user import UserRefDTO
from app.helpers.exceptions import InvalidRequest


class ProjectDTO(DTO):
    id: int
    name: str
    description: str | None
    enabled: bool
    revoked: bool
    default_dataset_id: int | None
    created_at: WireDatetime
    updated_at: WireDatetime
    owner: UserRefDTO | None
    # The group whose members alone may change it, null when it is open (ADR 0036)
    owner_group: str | None


class ProjectCreatedDTO(DTO):
    """The response of creating a project: its id."""
    id: int


class HealthCheckDTO(DTO):
    message: str
    status_code: int | None
    latency_ms: int | None


class RepositoryHealthDTO(DTO):
    id: int
    uri: str
    provider: str
    pr_count: int
    status: str
    health_check: HealthCheckDTO


class ResultsRepositoryHealthDTO(DTO):
    id: int
    uri: str
    owned_by_federated_node: bool
    target_dir: str
    base_branch: str
    status: str
    health_check: HealthCheckDTO


class ProjectHealthDTO(DTO):
    id: int
    name: str
    enabled: bool
    # ok only when there is at least one trigger repository and every repository, the
    # results one (if the project has one) included, is reachable
    status: str
    results_repository: ResultsRepositoryHealthDTO | None
    trigger_repositories: list[RepositoryHealthDTO]


class ProjectRequest(BaseModel):
    """A project as created. Fields it does not name are ignored."""
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    enabled: bool = False

    @model_validator(mode="before")
    @classmethod
    def revoked_is_patch_only(cls, data):
        """A project is created not revoked: revoking is a PATCH, by an admin."""
        if isinstance(data, dict) and "revoked" in data:
            raise ValueError("revoked is not accepted on create, revoke with PATCH")
        return data

    @field_validator("name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value

    @classmethod
    def parse(cls, body) -> "ProjectRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid project: {ve}") from ve


class ProjectPatchRequest(BaseModel):
    """The fields of a project that can be updated, all optional but never null. backfill is not stored."""
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool | None = None
    backfill: bool | None = None
    revoked: bool | None = None

    @model_validator(mode="after")
    def not_null(self):
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self


class ProjectResourceRequest(BaseModel):
    """A project's resource for a global dataset or secret as assigned: whether it is on."""
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = True


class ProjectResourcePatchRequest(BaseModel):
    """The fields of a project's dataset or secret resource that can be updated, all optional but never null."""
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool | None = None
    revoked: bool | None = None

    @model_validator(mode="after")
    def not_null(self):
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self
