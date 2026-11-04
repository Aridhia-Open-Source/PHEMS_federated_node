from pydantic import BaseModel, ConfigDict

from app.models.git_provider import GitProvider
from app.models.secret import Secret


class ResultsRepository(BaseModel):
    """
    A global git repository task results are delivered to, from backend API.

    - uri: the provider's uri and the repo_path, as the backend derives it.
    - repo_path: where the repository is on the provider's API (owner/name).
    - provider: the git host it is on.
    - secret: the secret holding the git credentials. Only the backend reads it, and mints the tokens from it.
    - enabled: turned on or off for the whole node.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    repo_path: str
    provider: GitProvider
    secret: Secret
    enabled: bool


class ProjectResultsRepository(BaseModel):
    """
    A project's resource for a global results repository, from backend API. Addressed by the
    global repository's id, results_repository.id, which a result's results_repository_id is.

    - project_id: the project the repository is assigned to.
    - results_repository: the global repository.
    - target_dir: the directory of the repository the project's results go under.
    - owned_by_federated_node: whether the node owns the repository.
    - enabled: a person turned the repository on for the project.
    - revoked: the controller withdrew the project's access.
    - active: the global repository is enabled, and the project resource is enabled and not revoked.
    """
    model_config = ConfigDict(extra="allow")

    project_id: int
    results_repository: ResultsRepository
    target_dir: str
    owned_by_federated_node: bool
    enabled: bool
    revoked: bool
    active: bool
