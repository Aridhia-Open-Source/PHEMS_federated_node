from app.dtos.base import DTO
from app.dtos.project import HealthCheckDTO
from app.models.secret_provider_type import SecretProviderType


class RepositoryConnectionDTO(DTO):
    """A global trigger or results repository, and whether it can be reached with its secret."""
    id: int
    uri: str
    provider: str
    enabled: bool
    status: str
    health_check: HealthCheckDTO


class GitProviderHealthDTO(DTO):
    """A global git provider, and whether its API answers."""
    id: int
    name: str
    type: str
    uri: str
    api_uri: str
    enabled: bool
    status: str
    health_check: HealthCheckDTO


class DatasetHealthDTO(DTO):
    """A global dataset, and whether the node can connect to its database with its secret."""
    id: int
    name: str
    host: str
    port: int
    type: str
    enabled: bool
    status: str
    health_check: HealthCheckDTO


class SecretHealthDTO(DTO):
    """
    A global secret, and whether it is in its store with the keys its datasets and
    repositories need. Key names only, never values.
    """
    label: str
    provider: SecretProviderType
    enabled: bool
    status: str
    health_check: HealthCheckDTO
    keys: list[str]
    missing_keys: list[str]


class ProjectDatasetHealthDTO(DTO):
    project_id: int
    enabled: bool
    revoked: bool
    active: bool
    dataset: DatasetHealthDTO


class ProjectSecretHealthDTO(DTO):
    project_id: int
    enabled: bool
    revoked: bool
    active: bool
    secret: SecretHealthDTO


class ProjectTriggerRepositoryHealthDTO(DTO):
    project_id: int
    pr_count: int
    enabled: bool
    revoked: bool
    active: bool
    trigger_repository: RepositoryConnectionDTO


class ProjectResultsRepositoryHealthDTO(DTO):
    project_id: int
    owned_by_federated_node: bool
    target_dir: str
    enabled: bool
    revoked: bool
    active: bool
    results_repository: RepositoryConnectionDTO


class GlobalHealthDTO(DTO):
    # ok only when every global resource of the four kinds is
    status: str
    datasets: list[DatasetHealthDTO]
    secrets: list[SecretHealthDTO]
    trigger_repositories: list[RepositoryConnectionDTO]
    results_repositories: list[RepositoryConnectionDTO]
