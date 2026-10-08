"""Merge status of a pull request."""

from enum import Enum


class MergeStatus(str, Enum):
    """
    Where a pull request stands on the git provider. A trigger `PullRequest` is always MERGED;
    a `PullRequestResult` starts OPEN.

    - OPEN: waiting for review.
    - MERGED: merged into the results repository's default branch.
    - CLOSED: closed without merging.
    """

    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"

    def __str__(self):
        return self.value
