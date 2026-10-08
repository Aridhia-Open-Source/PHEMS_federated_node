from pydantic import BaseModel, ConfigDict

from fncli.dagster.models.trigger_state import TriggerState


class PullRequestTrigger(BaseModel):
    """A merged pull request recorded as a trigger, from the backend API."""
    model_config = ConfigDict(extra="allow")

    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    payload: dict
    merge_commit_sha: str
    state: TriggerState
    state_cause: str | None = None
    task_id: int | None = None
