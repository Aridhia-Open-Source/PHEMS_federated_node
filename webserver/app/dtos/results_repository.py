from app.dtos.base import DTO
from app.dtos.secret import SecretRefDTO
from app.models.results_repository import ResultsRepository


class ResultsRepositoryDTO(DTO):
    id: int
    uri: str
    provider: str
    api_uri: str
    secret: SecretRefDTO
    target_dir: str
    project_id: int
    owned_by_federated_node: bool

    @classmethod
    def from_model(cls, obj: ResultsRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            provider=obj.provider,
            api_uri=obj.api_uri,
            secret=SecretRefDTO.from_model(obj.secret),
            target_dir=obj.target_dir,
            project_id=obj.project_id,
            owned_by_federated_node=obj.owned_by_federated_node,
        )
