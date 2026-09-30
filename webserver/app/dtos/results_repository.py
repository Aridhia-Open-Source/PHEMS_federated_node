from app.dtos.base import DTO


class ResultsRepositoryDTO(DTO):
    id: int
    uri: str
    owned_by_federated_node: bool
