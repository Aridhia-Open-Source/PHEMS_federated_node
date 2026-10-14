from enum import Enum


class ResultState(str, Enum):
    """
    How the delivery of a task's results is going, as the webserver defines it.

    IN_PROGRESS: the delivery is under way, or not started. A failed one that is re-launched
        is IN_PROGRESS again.
    DELIVERED: the pull request is opened. Its merge or close is tracked in the step.
    FAILED: the delivery failed, and nothing retries it.
    """

    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
