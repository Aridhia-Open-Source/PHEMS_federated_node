from pydantic import BaseModel, ConfigDict


class PullRequest(BaseModel):
    """The provider's facts of a merged pull request, stored once per repository, from the backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    merge_commit_sha: str
    base_branch: str
    files_truncated: bool
