from pydantic import BaseModel, ConfigDict

from app.models.trigger_state import TriggerState


class PullRequestTrigger(BaseModel):
    """A project's trigger for a merged pull request, from the backend API."""
    model_config = ConfigDict(extra="allow")

    project_id: int
    project_trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    merge_commit_sha: str
    state: TriggerState
    state_cause: str | None = None
    task_id: int | None = None
