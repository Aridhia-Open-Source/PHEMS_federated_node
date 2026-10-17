"""Pull request result step enum."""

from enum import Enum


class PullRequestResultStep(str, Enum):
    """
    The furthest step the delivery of a task's results by pull request has reached. It only
    moves forward: UNKNOWN < PUSHED < OPENED < MERGED, CLOSED or REVOKED, the last three
    terminal and of equal rank.

    - UNKNOWN: the result is recorded, nothing is delivered yet.
    - PUSHED: the results are pushed to their branch on the results repository.
    - OPENED: the pull request from that branch is opened.
    - MERGED: the pull request is merged, as the sync sensor finds on the provider.
    - CLOSED: the pull request is closed without merging, as the sync sensor finds on the provider.
    - REVOKED: the project's link to the results repository was revoked, so the results are never delivered. Final:
      un-revoking the link does not deliver them.
    """

    UNKNOWN = "UNKNOWN"
    PUSHED = "PUSHED"
    OPENED = "OPENED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"

    def __str__(self):
        return self.value
