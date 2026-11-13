from pydantic import BaseModel, ConfigDict

from app.models.trigger_state import TriggerState


class PullRequestTrigger(BaseModel):
    """A project's trigger for a merged pull request, from the backend API."""
    model_config = ConfigDict(extra="allow")

    project_id: int
    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    merge_commit_sha: str
    state: TriggerState
    state_cause: str | None = None
    task_id: int | None = None
    # Paths of the new spec files under the project resource's watch_dir, matched by the backend
    spec_files: list[str]


class TriggerRepositoryRef(BaseModel):
    """A trigger repository named by where it is, nested in the trigger of a task."""
    model_config = ConfigDict(extra="allow")

    id: int
    repo_path: str
    uri: str


class TaskTrigger(PullRequestTrigger):
    """The pull request that yielded a task, with the repository it was merged in."""
    trigger_repository: TriggerRepositoryRef
    # The text of the pull request's spec file, exactly as it was merged
    spec_raw: str
