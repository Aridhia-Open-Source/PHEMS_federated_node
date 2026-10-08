from pydantic import BaseModel, ConfigDict, Field

from fncli.dagster.models.secret import Secret
from fncli.dagster.models.pull_request_trigger import PullRequestTrigger


class TriggerRepository(BaseModel):
    """
    A repository the node watches. Named for which kind it is: the GitHub repo a delivery
    target writes to is the other kind, and lives in delivery_targets.config.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    # The secret holding the git token, under the key TOKEN.
    secret: Secret
    watch_dir: str
    base_branch: str
    project_id: int
    # From the project's default dataset, so a project without one has none.
    dataset_id: int | None = None
    initial_cursor: str | None = None
    pr_cursor: str
    pr_count: int = 0
    pull_requests: list[PullRequestTrigger] = Field(default_factory=list)

    @property
    def repo_path(self) -> str:
        """
        Where the repository is on the provider's API (owner/repo): the last two path
        segments of the uri. Right for GitHub and Gitea; GitLab nested groups, Bitbucket
        Server and Azure DevOps need provider-specific handling.
        """
        return "/".join(self.uri.removesuffix("/").removesuffix(".git").split("/")[-2:])
