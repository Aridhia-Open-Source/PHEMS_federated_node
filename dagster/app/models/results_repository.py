from pydantic import BaseModel, ConfigDict

from app.models.secret import Secret


class ResultsRepository(BaseModel):
    """
    The git repository a project's task results are delivered to.

    - uri: host and path without a scheme, as the backend stores it.
    - api_uri: the provider's API, whose scheme the clone URL borrows.
    - secret: the secret holding the git token, under the key TOKEN.
    - target_dir: the directory of the repository the results go under.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    secret: Secret
    target_dir: str
    project_id: int
