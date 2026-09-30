from pydantic import BaseModel, ConfigDict


class TaskRequest(BaseModel):
    """Task request data from backend API. Raised by a pull request or an API request."""
    model_config = ConfigDict(extra="allow")

    id: int
    pull_request_id: int | None = None
    api_request_id: int | None = None
    project_id: int
    queued: bool
    payload: dict
