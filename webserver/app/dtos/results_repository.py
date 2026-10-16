from app.dtos.base import DTO
from app.dtos.secret import SecretDTO
from app.models.project_results_repository import ProjectResultsRepository
from app.models.results_repository import ResultsRepository


class ResultsRepositoryDTO(DTO):
    id: int
    uri: str
    provider: str
    api_uri: str
    secret: SecretDTO

    @classmethod
    def from_model(cls, obj: ResultsRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            provider=obj.provider,
            api_uri=obj.api_uri,
            secret=SecretDTO.from_model(obj.secret),
        )


class ProjectResultsRepositoryDTO(DTO):
    """A project's assignment of a global results repository, the repository nested."""
    id: int
    project_id: int
    results_repository: ResultsRepositoryDTO
    target_dir: str
    owned_by_federated_node: bool
    enabled: bool
    revoked: bool
    active: bool

    @classmethod
    def from_model(cls, obj: ProjectResultsRepository):
        return cls(
            id=obj.id,
            project_id=obj.project_id,
            results_repository=ResultsRepositoryDTO.from_model(obj.results_repository),
            target_dir=obj.target_dir,
            owned_by_federated_node=obj.owned_by_federated_node,
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
        )
