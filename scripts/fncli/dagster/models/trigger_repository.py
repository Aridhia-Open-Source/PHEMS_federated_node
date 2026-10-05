from pydantic import BaseModel, ConfigDict, Field

from .secret_type import SecretType
from .pull_request import PullRequest


class TriggerRepository(BaseModel):
    """
    A repository the node watches. Named for which kind it is: the GitHub repo a delivery
    target writes to is the other kind, and lives in delivery_targets.config.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    repo_path: str
    provider: str
    api_uri: str
    # The project-local name of the secret holding the git token, under the key TOKEN.
    secret_name: str
    secret_type: SecretType
    # What the secret is called in its store: the name is local to the project.
    secret_store_name: str
    watch_dir: str
    base_branch: str
    project_id: int
    # From the project's default dataset, so a project without one has none.
    dataset_id: int | None = None
    initial_cursor: str | None = None
    pr_cursor: str
    pr_count: int = 0
    pull_requests: list[PullRequest] = Field(default_factory=list)
