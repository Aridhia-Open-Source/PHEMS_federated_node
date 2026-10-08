from app.dtos.base import DTO, WireDatetime


class ProjectDTO(DTO):
    id: int
    name: str
    description: str | None
    enabled: bool
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
