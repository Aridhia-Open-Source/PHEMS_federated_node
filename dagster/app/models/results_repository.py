from pydantic import BaseModel, ConfigDict

from app.git_uri import normalise_repo_uri
from app.models.secret import Secret


class ResultsRepository(BaseModel):
    """
    A global git repository task results are delivered to, from backend API.

    - uri: host and path without a scheme, as the backend stores it.
    - api_uri: the provider's API, whose scheme the clone URL borrows.
    - secret: the secret holding the git token, under the key TOKEN.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    secret: Secret

    @property
    def repo_path(self) -> str:
        """Where the repository is on the provider's API (owner/repo), as TriggerRepository.repo_path."""
        return "/".join(normalise_repo_uri(self.uri).split("/")[-2:])


class ProjectResultsRepository(BaseModel):
    """
    A project's assignment of a global results repository, from backend API.

    - id: the assignment's id, which a result's results_repository_id points at.
    - project_id: the project the repository is assigned to.
    - results_repository: the global repository.
    - target_dir: the directory of the repository the project's results go under.
    - owned_by_federated_node: whether the node owns the repository.
    - enabled: a person turned the repository on for the project.
    - revoked: the controller withdrew the project's access.
    - active: enabled and not revoked.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    project_id: int
    results_repository: ResultsRepository
    target_dir: str
    owned_by_federated_node: bool
    enabled: bool
    revoked: bool
    active: bool
