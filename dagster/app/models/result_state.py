from enum import Enum


class ResultState(str, Enum):
    """
    How the delivery of a task's results is going, as nexus-api defines it.

    IN_PROGRESS: the delivery is under way, or not started. A failed one that is re-launched
        is IN_PROGRESS again.
    DELIVERED: the branch is pushed. The results pull request, opened and then merged or closed, is
        tracked in the step.
    FAILED: the delivery failed, and results_delivery_retry_sensor retries it unless its step is final.
    """

    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
