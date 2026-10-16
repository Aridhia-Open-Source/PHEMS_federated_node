from pydantic import BaseModel, ConfigDict

from fncli.dagster.models.secret import Secret


class ResultsRepository(BaseModel):
    """
    A global repository the node writes task results to.

    - uri: the repository, with the scheme stripped as the backend stores it.
    - secret: the secret holding the git token, under the key TOKEN.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    secret: Secret


class ProjectResultsRepository(BaseModel):
    """
    A project's assignment of a global results repository.

    - id: the assignment's id, which a result's results_repository_id points at.
    - results_repository: the global repository.
    - target_dir: the directory in the repository the project's results go under.
    - owned_by_federated_node: whether the node created, and so manages, the repository.
    - enabled: a person turned the repository on for the project.
    - revoked: the controller withdrew the project's access.
    - active: enabled and not revoked.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    project_id: int
    results_repository: ResultsRepository
    target_dir: str
    owned_by_federated_node: bool = True
    enabled: bool
    revoked: bool
    active: bool
