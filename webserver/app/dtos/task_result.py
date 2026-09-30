from app.dtos.base import DTO, WireDatetime


class TaskResultDTO(DTO):
    id: int
    task_id: int
    results_repository_id: int
    status: str
    attempts: int
    branch: str | None
    commit_sha: str | None
    pull_request_number: int | None
    pull_request_url: str | None
    error: str | None
    created_at: WireDatetime
    updated_at: WireDatetime
