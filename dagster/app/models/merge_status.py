from enum import Enum


class MergeStatus(str, Enum):
    """
    The state of the pull request a task's results were delivered in, as the webserver defines it.

    OPEN: waiting for review.
    MERGED: merged into the results repository's default branch.
    CLOSED: closed without merging.
    """

    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"

    @classmethod
    def from_git(cls, pr: dict) -> "MergeStatus":
        """The state of a pull request, from the git provider's response."""
        if pr["merged_at"]:
            return cls.MERGED
        if pr["state"] == "closed":
            return cls.CLOSED
        return cls.OPEN
