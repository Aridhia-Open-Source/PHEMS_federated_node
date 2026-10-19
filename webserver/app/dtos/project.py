from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.dtos.base import DTO, WireDatetime
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
