from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dtos.base import DTO, NaiveUtcDatetime, WireDatetime
from app.models.pull_request_result_step import PullRequestResultStep
from app.models.result import Result
from app.models.result_state import ResultState


class ResultDTO(DTO):
    id: int
    type: str
    task_id: int
    project_id: int
    results_repository_id: int
    attempts: int
    error: str | None
    created_at: WireDatetime
    updated_at: WireDatetime

    @classmethod
    def from_model(cls, obj: Result):
        dto = super().from_model(obj)
        # The global repository, not the project's resource row the result is stored against
        dto.results_repository_id = obj.assignment.results_repository_id
        return dto


class PullRequestResultDTO(ResultDTO):
    step: str
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


class ResultPatchRequest(BaseModel):
    """
    The progress of a result's delivery. The fields of a pull request result, from step on, are refused
    for any other type of result. Null clears a field that can be empty, the others cannot be null.
    """
    model_config = ConfigDict(extra="forbid", strict=True)

    attempts: int | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=1024)
    step: PullRequestResultStep | None = Field(default=None, strict=False)
    state: ResultState | None = Field(default=None, strict=False)
    branch: str | None = Field(default=None, max_length=256)
    commit_sha: str | None = Field(default=None, max_length=40)
    number: int | None = Field(default=None, ge=0)
    url: str | None = Field(default=None, max_length=4096)
    merged_at: NaiveUtcDatetime | None = None
    merge_commit_sha: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def not_null(self):
        not_nullable = {"attempts", "step", "state", "number"}
        nulls = sorted(f for f in self.model_fields_set & not_nullable if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self


class ResultRequest(BaseModel):
    """A result in a create request: the delivery of a task's results to a results repository, the global one's id."""
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: int
    results_repository_id: int
