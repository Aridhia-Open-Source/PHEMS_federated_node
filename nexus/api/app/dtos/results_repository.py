from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dtos.base import DTO
from app.dtos.git_provider import GitProviderRefDTO
from app.dtos.secret import SecretDTO
from app.models.project_results_repository import ProjectResultsRepository
from app.models.results_repository import ResultsRepository


class ResultsRepositoryDTO(DTO):
    id: int
    uri: str
    repo_path: str
    provider: GitProviderRefDTO
    secret: SecretDTO
    enabled: bool
    revoked: bool

    @classmethod
    def from_model(cls, obj: ResultsRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            repo_path=obj.repo_path,
            provider=GitProviderRefDTO.from_model(obj.provider),
            secret=SecretDTO.from_model(obj.secret),
            enabled=obj.enabled,
            revoked=obj.revoked,
        )


class ProjectResultsRepositoryDTO(DTO):
    """A project's resource for a global results repository, the repository nested. Addressed by the repository's id."""
    project_id: int
    results_repository: ResultsRepositoryDTO
    target_dir: str
    base_branch: str
    owned_by_federated_node: bool
    enabled: bool
    revoked: bool
    active: bool

    @classmethod
    def from_model(cls, obj: ProjectResultsRepository):
        return cls(
            project_id=obj.project_id,
            results_repository=ResultsRepositoryDTO.from_model(obj.results_repository),
            target_dir=obj.target_dir,
            base_branch=obj.base_branch,
            owned_by_federated_node=obj.owned_by_federated_node,
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
        )


class ProjectResultsRepositoryRequest(BaseModel):
    """A project's resource for a global results repository as assigned: where its results go, and whether it is on."""
    model_config = ConfigDict(extra="forbid", strict=True)

    target_dir: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    owned_by_federated_node: bool = True
    enabled: bool = True


class ProjectResultsRepositoryPatchRequest(BaseModel):
    """The fields of a project's results repository resource that can be updated, all optional but never null."""
    model_config = ConfigDict(extra="forbid", strict=True)

    target_dir: str | None = None
    base_branch: str | None = Field(default=None, min_length=1)
    owned_by_federated_node: bool | None = None
    enabled: bool | None = None
    revoked: bool | None = None

    @model_validator(mode="after")
    def not_null(self):
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self
