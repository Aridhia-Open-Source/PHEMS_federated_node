from pydantic import BaseModel, ConfigDict

from app.models.pull_request_result_state import PullRequestResultState


class PullRequestResult(BaseModel):
    """
    The delivery of one task's results to one results repository by a pull request we open,
    not the merged PullRequestTrigger we watch. The webserver's Result of type PR.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    type: str
    task_id: int
    results_repository_id: int
    state: PullRequestResultState
    attempts: int
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    number: int | None = None
    url: str | None = None
    merged_at: str | None = None
    merge_commit_sha: str | None = None
