from pydantic import BaseModel, ConfigDict

from fncli.dagster.models.secret import Secret


class ResultsRepository(BaseModel):
    """
    A global repository the node writes task results to.

    - uri: the repository, with the scheme stripped as the backend stores it.
    - secret: the secret holding the git token, under the key TOKEN.
    - enabled: turned on or off for the whole node.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    secret: Secret
    enabled: bool


class ProjectResultsRepository(BaseModel):
    """
    A project's link to a global results repository. Addressed by the global repository's id,
    results_repository.id, which a result's results_repository_id is.

    - results_repository: the global repository.
    - target_dir: the directory in the repository the project's results go under.
    - owned_by_federated_node: whether the node created, and so manages, the repository.
    - enabled: a person turned the repository on for the project.
    - revoked: the controller withdrew the project's access.
    - active: the global repository is enabled, and the link is enabled and not revoked.
    """
    model_config = ConfigDict(extra="allow")

    project_id: int
    results_repository: ResultsRepository
    target_dir: str
    owned_by_federated_node: bool = True
    enabled: bool
    revoked: bool
    active: bool
