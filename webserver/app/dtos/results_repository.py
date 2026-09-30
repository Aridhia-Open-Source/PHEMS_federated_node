from app.dtos.base import DTO
from app.models.results_repository import ResultsRepository


class ResultsRepositoryDTO(DTO):
    id: int
    uri: str
    repo_path: str
    provider: str
    api_uri: str
    k8s_secret_name: str
    k8s_secret_k8s_name: str
    target_dir: str
    project_id: int
    owned_by_federated_node: bool

    @classmethod
    def from_model(cls, obj: ResultsRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            repo_path=obj.repo_path,
            provider=obj.provider,
            api_uri=obj.api_uri,
            k8s_secret_name=obj.k8s_secret_name,
            k8s_secret_k8s_name=obj.k8s_secret_k8s_name,
            target_dir=obj.target_dir,
            project_id=obj.project_id,
            owned_by_federated_node=obj.owned_by_federated_node,
        )
