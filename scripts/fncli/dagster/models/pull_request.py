from pydantic import BaseModel, ConfigDict

from .trigger_state import TriggerState


class PullRequest(BaseModel):
    """Pull Request data from backend API."""
    model_config = ConfigDict(extra="allow")

    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    payload: dict
    merge_commit_sha: str
    state: TriggerState
    reason: str | None = None
    task_id: int | None = None
