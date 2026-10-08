from pydantic import BaseModel, ConfigDict

from app.models.merge_status import MergeStatus
from app.models.task_result_status import TaskResultStatus


class TaskResult(BaseModel):
    """
    The delivery of one task's results to one results repository. type PR is a
    PullRequestResult on the webserver: the pull request we open to deliver the results,
    not the merged trigger PullRequest we watch.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    type: str
    task_id: int
    results_repository_id: int
    status: TaskResultStatus
    attempts: int
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    number: int | None = None
    url: str | None = None
    merge_status: MergeStatus | None = None
    merged_at: str | None = None
    merge_commit_sha: str | None = None
