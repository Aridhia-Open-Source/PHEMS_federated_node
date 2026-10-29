"""Task status and trigger provenance enums."""

from enum import Enum


class TaskStatus(str, Enum):
    """
    The canonical status of a task run and of a delivery attempt. Dagster's own vocabulary
    is mapped into this and never stored.
    """

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

    def __str__(self):
        return self.value


# The moves allowed from each status. Forward only: the run-status sensors can see a run start
# before it is queued, and a task can finish from any unfinished status. SUCCESS, FAILED and
# CANCELED are final, only a retry (RETRYABLE) queues the task again.
TASK_MOVES = {
    TaskStatus.PENDING.value: {
        TaskStatus.QUEUED.value, TaskStatus.RUNNING.value, TaskStatus.SUCCESS.value,
        TaskStatus.FAILED.value, TaskStatus.CANCELED.value,
    },
    TaskStatus.QUEUED.value: {
        TaskStatus.RUNNING.value, TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELED.value,
    },
    TaskStatus.RUNNING.value: {TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELED.value},
    TaskStatus.SUCCESS.value: set(),
    TaskStatus.FAILED.value: set(),
    TaskStatus.CANCELED.value: set(),
}
RETRYABLE = {TaskStatus.FAILED.value, TaskStatus.CANCELED.value}


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
