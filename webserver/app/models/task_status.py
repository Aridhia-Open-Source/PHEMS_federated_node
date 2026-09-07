"""Task status and trigger provenance enums."""

from enum import Enum


class TaskStatus(str, Enum):
    """
    The canonical status of a task run and of a delivery attempt. Dagster's own vocabulary
    is mapped into this and never stored; so are the legacy lowercase values (`scheduled`,
    `running`, `cancelled`, `deleted`) that Task.get_status() renders on the wire.
    """

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"

    def __str__(self):
        return self.value


class TriggerSource(str, Enum):
    """
    What caused a task to exist. Either the task was submitted through the API or a merged
    pull request produced it. Descriptive only - it outlives the triggering pull request,
    so no constraint ties it to the PR columns.
    """

    API = "API"
    PR = "PR"

    def __str__(self):
        return self.value
