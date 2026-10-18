"""Pull request result step enum."""

from enum import Enum


class PullRequestResultStep(str, Enum):
    """
    The furthest step the delivery of a task's results by pull request has reached. It only
    moves forward: UNKNOWN < PUSHED < OPENED < MERGED, CLOSED, REVOKED or STALE, the last four
    terminal and of equal rank.

    - UNKNOWN: the result is recorded, nothing is delivered yet.
    - PUSHED: the results are pushed to their branch on the results repository.
    - OPENED: the pull request from that branch is opened.
    - MERGED: the pull request is merged, as the sync sensor finds on the provider.
    - CLOSED: the pull request is closed without merging, as the sync sensor finds on the provider.
    - REVOKED: the project's link to the results repository was revoked, so the results are never delivered. Final:
      un-revoking the link does not deliver them.
    - STALE: the task's configuration changed after it was created, so nothing is delivered. Final.
    """

    UNKNOWN = "UNKNOWN"
    PUSHED = "PUSHED"
    OPENED = "OPENED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    STALE = "STALE"

    def __str__(self):
        return self.value


# A step only moves to a higher rank (ADR 0008). MERGED, CLOSED, REVOKED and STALE are terminal and of
# equal rank, so none moves to another.
RESULT_ORDER = {
    PullRequestResultStep.UNKNOWN.value: 0,
    PullRequestResultStep.PUSHED.value: 1,
    PullRequestResultStep.OPENED.value: 2,
    PullRequestResultStep.MERGED.value: 3,
    PullRequestResultStep.CLOSED.value: 3,
    PullRequestResultStep.REVOKED.value: 3,
    PullRequestResultStep.STALE.value: 3,
}
