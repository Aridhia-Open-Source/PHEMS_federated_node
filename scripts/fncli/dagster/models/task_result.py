from pydantic import BaseModel, ConfigDict


class TaskResult(BaseModel):
    """
    A task's results delivery to a results repository, from the backend API. `type` 'PR' is
    a delivery as a pull request we open in the results repo (not the trigger-side
    PullRequest we watch); its fields fill in as the delivery goes.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    type: str
    task_id: int
    results_repository_id: int
    status: str
    attempts: int
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    number: int | None = None
    url: str | None = None
    # OPEN, MERGED or CLOSED, kept fresh by results_pull_request_sync_sensor.
    merge_status: str | None = None
    merged_at: str | None = None
    merge_commit_sha: str | None = None
