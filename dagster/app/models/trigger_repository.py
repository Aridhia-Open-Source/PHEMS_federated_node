from pydantic import BaseModel, ConfigDict, Field

from app.git_uri import normalise_repo_uri
from app.models.secret import Secret
from app.models.pull_request_trigger import PullRequestTrigger


class TriggerRepository(BaseModel):
    """
    A global repository the node watches, from backend API. Named for which kind it is: the
    GitHub repo a delivery target writes to is the other kind, and lives in delivery_targets.config.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    provider: str
    api_uri: str
    # The secret holding the git token, under the key TOKEN.
    secret: Secret
    # The latest merge among the stored pull requests, None while there are none
    pr_cursor: str | None = None

    @property
    def repo_path(self) -> str:
        """
        Where the repository is on the provider's API (owner/repo): the last two path
        segments of the uri. Right for GitHub and Gitea; GitLab nested groups, Bitbucket
        Server and Azure DevOps need provider-specific handling.
        """
        return "/".join(normalise_repo_uri(self.uri).split("/")[-2:])


class ProjectTriggerRepository(BaseModel):
    """
    A project's assignment of a global trigger repository, from backend API.

    - id: the assignment's id, which a pull request's project_trigger_repository_id points at.
    - project_id: the project the repository is assigned to.
    - trigger_repository: the global repository.
    - dataset_id: from the project's default dataset, so a project without one has none.
    - enabled: a person turned the repository on for the project.
    - revoked: the controller withdrew the project's access.
    - active: enabled and not revoked.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    project_id: int
    trigger_repository: TriggerRepository
    watch_dir: str
    base_branch: str
    dataset_id: int | None = None
    initial_cursor: str | None = None
    pr_cursor: str
    pr_count: int = 0
    enabled: bool
    revoked: bool
    active: bool
    pull_requests: list[PullRequestTrigger] = Field(default_factory=list)

    @property
    def repo_path(self) -> str:
        """The nested repository's repo_path."""
        return self.trigger_repository.repo_path
