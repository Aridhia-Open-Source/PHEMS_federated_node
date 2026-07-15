"""Pull request processing status enum."""

from enum import Enum


class PullRequestStatus(str, Enum):
    """Status of a pull request in the ingestion and processing pipeline."""

    UNPROCESSED = "unprocessed"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"

    def __str__(self):
        return self.value
