"""Result state enum."""

from enum import Enum


class ResultState(str, Enum):
    """
    How the delivery of a task's results is going, apart from the step it has reached.

    - IN_PROGRESS: the delivery is under way, or not started. A new result, and a failed one
      that is re-launched, are IN_PROGRESS.
    - DELIVERED: the branch is pushed. The results pull request, opened and then merged or closed,
      is tracked in the step.
    - FAILED: the delivery failed, and nothing retries it.
    """

    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"

    def __str__(self):
        return self.value
