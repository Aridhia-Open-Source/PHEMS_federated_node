from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.models.trigger_state import TriggerState


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

    # The server owns these: it records a new PR as UNKNOWN
    SERVER_FIELDS: ClassVar[set[str]] = {"trigger_repository_id", "state", "state_cause", "task_id"}

    @classmethod
    def from_git(cls, trigger_repository_id: int, pr: dict) -> "PullRequestTrigger":
        """A newly merged pull request, from the git provider's response."""
        return cls(
            trigger_repository_id=trigger_repository_id,
            number=pr["number"],
            title=pr["title"],
            raised_by=pr["user"]["login"],
            merged_at=pr["merged_at"],
            merge_commit_sha=pr["merge_commit_sha"],
            state=TriggerState.UNKNOWN,
            payload={},
        )

    def dump_new(self) -> dict:
        """The body to save a new pull request with."""
        return self.model_dump(exclude=self.SERVER_FIELDS)
