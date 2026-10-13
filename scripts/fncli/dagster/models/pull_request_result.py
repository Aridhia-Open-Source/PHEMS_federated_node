from pydantic import BaseModel, ConfigDict


class PullRequestResult(BaseModel):
    """
    A task's results delivery to a results repository, from the backend API: the pull
    request we open in the results repo (not the trigger-side PullRequestTrigger we watch).
    Its fields fill in as the delivery goes.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    type: str
    task_id: int
    results_repository_id: int
    # The furthest delivery step reached: UNKNOWN, PUSHED, OPENED, then MERGED or CLOSED,
    # the last two kept fresh by results_pull_request_sync_sensor.
    state: str
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
