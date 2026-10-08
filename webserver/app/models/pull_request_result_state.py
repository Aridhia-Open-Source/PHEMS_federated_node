"""Pull request result state enum."""

from enum import Enum


class PullRequestResultState(str, Enum):
    """
    The furthest step the delivery of a task's results by pull request has reached. It only
    moves forward: UNKNOWN < PUSHED < OPENED < MERGED or CLOSED, the last two terminal and
    of equal rank.

    - UNKNOWN: the result is recorded, nothing is delivered yet.
    - PUSHED: the results are pushed to their branch on the results repository.
    - OPENED: the pull request from that branch is opened.
    - MERGED: the pull request is merged, as the sync sensor finds on the provider.
    - CLOSED: the pull request is closed without merging, as the sync sensor finds on the provider.
    """

    UNKNOWN = "UNKNOWN"
    PUSHED = "PUSHED"
    OPENED = "OPENED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"

    def __str__(self):
        return self.value
