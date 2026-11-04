"""Result state enum."""

from enum import Enum


class ResultState(str, Enum):
    """
    How the delivery of a task's results is going, apart from the step it has reached.

    - IN_PROGRESS: the delivery is under way, or not started. A new result, and a failed one
      that is re-launched, are IN_PROGRESS.
    - DELIVERED: the results are delivered, the pull request is opened. Its merge or close is
      the pull request's own lifecycle, tracked in the step.
    - FAILED: the delivery failed, and nothing retries it.
    """

    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"

    def __str__(self):
        return self.value
