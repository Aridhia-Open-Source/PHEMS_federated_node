from datetime import datetime

from app.dtos.base import DTO, WireDatetime
from app.models.result import Result


class ResultDTO(DTO):
    id: int
    type: str
    task_id: int
    results_repository_id: int
    attempts: int
    error: str | None
    created_at: WireDatetime
    updated_at: WireDatetime


class PullRequestResultDTO(ResultDTO):
    state: str
    branch: str | None
    commit_sha: str | None
    number: int | None
    url: str | None
    merged_at: datetime | None
    merge_commit_sha: str | None


DTO_BY_TYPE = {'PR': PullRequestResultDTO}


def dump_result(obj: Result) -> dict:
    """The response of a result, in the shape of its type."""
    return DTO_BY_TYPE[obj.type].from_model(obj).dump()
