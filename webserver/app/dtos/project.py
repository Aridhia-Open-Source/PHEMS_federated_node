from app.dtos.base import DTO, WireDatetime
from app.dtos.results_repository import ResultsRepositoryDTO


class ProjectDTO(DTO):
    id: int
    name: str
    description: str | None
    enabled: bool
    default_dataset_id: int | None
    results_repository_id: int | None
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


class ProjectHealthDTO(DTO):
    id: int
    name: str
    enabled: bool
    # ok only when there is at least one repository and every one of them is reachable
    status: str
    results_repository: ResultsRepositoryDTO | None
    trigger_repositories: list[RepositoryHealthDTO]
