from pydantic import BaseModel, ConfigDict

from fncli.dagster.models.secret import Secret


class ResultsRepository(BaseModel):
    """
    A repository the node writes a project's task results to.

    - uri: the repository, with the scheme stripped as the backend stores it.
    - secret: the secret holding the git token, under the key TOKEN.
    - target_dir: the directory in the repository the results go under.
    - owned_by_federated_node: whether the node created, and so manages, the repository.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    secret: Secret
    target_dir: str
    project_id: int
    owned_by_federated_node: bool = True
