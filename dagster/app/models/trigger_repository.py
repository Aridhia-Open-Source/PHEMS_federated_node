from pydantic import BaseModel, ConfigDict, Field

from app.models.git_provider import GitProvider
from app.models.secret import Secret
from app.models.pull_request_trigger import PullRequestTrigger


class TriggerRepository(BaseModel):
    """
    A global repository the node watches, from backend API. Named for which kind it is: the
    GitHub repo a delivery target writes to is the other kind, and lives in delivery_targets.config.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    # The provider's uri and the repo_path, as the backend derives it.
    uri: str
    # Where the repository is on the provider's API (owner/name).
    repo_path: str
    provider: GitProvider
    # The secret holding the git token, under the key TOKEN.
    secret: Secret
    # Turned on or off for the whole node. A disabled repository is not polled.
    enabled: bool
    # Where polling the provider resumes: the latest stored merge, or with none stored the
    # earliest cursor of its active links. None if there is neither.
    pr_cursor: str | None = None


class ProjectTriggerRepository(BaseModel):
    """
    A project's link to a global trigger repository, from backend API. Addressed by the
    global repository's id, trigger_repository.id.

    - project_id: the project the repository is linked to.
    - trigger_repository: the global repository.
    - dataset_id: from the project's default dataset, so a project without one has none.
    - enabled: a person turned the repository on for the project.
    - revoked: the controller withdrew the project's access.
    - active: the global repository is enabled, and the link is enabled and not revoked.
    """

    model_config = ConfigDict(extra="allow")

    project_id: int
    trigger_repository: TriggerRepository
    watch_dir: str
    base_branch: str
    dataset_id: int | None = None
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
