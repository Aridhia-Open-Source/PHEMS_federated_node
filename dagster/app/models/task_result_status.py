from enum import Enum


class TaskResultStatus(str, Enum):
    """The status of delivering a task's results to a destination, as the webserver defines it."""

    PENDING = "PENDING"
    PUSHED = "PUSHED"
    PR_OPENED = "PR_OPENED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
