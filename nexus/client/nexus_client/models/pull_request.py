from pydantic import BaseModel, ConfigDict

# GitHub lists at most 3000 changed files of a pull request, so a list that long may be cut short.
PROVIDER_FILES_CAP = 3000


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


class ChangedFile(BaseModel):
    """A file a pull request changed: its path and how (added, modified...). Never its content."""
    path: str
    status: str


class NewPullRequest(BaseModel):
    """A merged pull request to ingest: the provider's facts and the files it changed."""
    number: int
    title: str
    raised_by: str
    merged_at: str
    merge_commit_sha: str
    base_branch: str
    files_truncated: bool
    changed_files: list[ChangedFile]

    @classmethod
    def from_git(cls, pr: dict, files: list[dict]) -> "NewPullRequest":
        """A newly merged pull request, from the git provider's response and its list of changed files."""
        return cls(
            number=pr["number"],
            title=pr["title"],
            raised_by=pr["user"]["login"],
            merged_at=pr["merged_at"],
            merge_commit_sha=pr["merge_commit_sha"],
            base_branch=pr["base"]["ref"],
            files_truncated=len(files) >= PROVIDER_FILES_CAP,
            changed_files=[ChangedFile(path=f["filename"], status=f["status"]) for f in files],
        )
