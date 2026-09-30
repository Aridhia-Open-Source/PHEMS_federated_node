"""Task result delivery status enum."""

from enum import Enum


class TaskResultStatus(str, Enum):
    """Status of delivering one task's results to one destination.

    - PENDING: Delivery not yet attempted
    - PUSHED: Results pushed to a branch on the destination
    - PR_OPENED: Pull request raised upstream, not merged
    - DELIVERED: Results committed to the local destination
    - FAILED: Delivery failed, see the error
    """

    PENDING = "PENDING"
    PUSHED = "PUSHED"
    PR_OPENED = "PR_OPENED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"

    def __str__(self):
        return self.value
