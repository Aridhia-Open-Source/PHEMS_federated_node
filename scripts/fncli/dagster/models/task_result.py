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
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    # OPEN, MERGED or CLOSED, kept fresh by results_pull_request_sync_sensor.
    pull_request_state: str | None = None
    merged_at: str | None = None
    merge_commit_sha: str | None = None
