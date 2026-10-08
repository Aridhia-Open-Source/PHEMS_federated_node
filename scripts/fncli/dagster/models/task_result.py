from pydantic import BaseModel, ConfigDict


class TaskResult(BaseModel):
    """A task's results delivery to a results repository, from the backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    task_id: int
    results_repository_id: int
    status: str
    attempts: int
    branch: str | None = None
    commit_sha: str | None = None
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    error: str | None = None
