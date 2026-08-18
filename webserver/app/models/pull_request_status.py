"""Pull request processing status enum."""

from enum import Enum


class PullRequestStatus(str, Enum):
    """Status of a pull request in the ingestion and processing pipeline.

    Internal statuses (set by ingest/trigger sensors):
    - UNKNOWN: Not yet validated
    - IGNORED: Doesn't match watch criteria
    - INVALID: Bad spec or validation failed
    - READY: Validated and handed to Dagster (prevents re-pickup)

    Job lifecycle statuses (mapped from Dagster run events):
    - QUEUED: Dagster job queued
    - STARTED: Dagster job started
    - SUCCESS: Dagster job succeeded
    - FAILURE: Dagster job failed
    - CANCELLED: Dagster job cancelled

    
    TODO: Move the job lifecycle values to tasks.status
    """

    UNKNOWN = "UNKNOWN"
    IGNORED = "IGNORED"
    INVALID = "INVALID"
    READY = "READY"
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"

    def __str__(self):
        return self.value
