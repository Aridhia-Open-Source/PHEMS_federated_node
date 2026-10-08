"""Pull request result state enum."""

from enum import Enum


class MergeStatus(str, Enum):
    """
    Where the pull request we opened to deliver a task's results stands on the git provider.

    - OPEN: waiting for review.
    - MERGED: merged into the results repository's default branch.
    - CLOSED: closed without merging.
    """

    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"

    def __str__(self):
        return self.value
