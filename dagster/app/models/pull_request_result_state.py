from enum import Enum


class PullRequestResultState(str, Enum):
    """
    The furthest step the delivery of a task's results by pull request has reached, as the
    webserver defines it. It only moves forward, and the webserver rejects a move back.

    UNKNOWN: the result is recorded, nothing is delivered yet.
    PUSHED: the results are pushed to their branch.
    OPENED: the pull request from that branch is opened.
    MERGED: the pull request is merged into the results repository's default branch.
    CLOSED: the pull request is closed without merging.
    """

    UNKNOWN = "UNKNOWN"
    PUSHED = "PUSHED"
    OPENED = "OPENED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"

    @classmethod
    def from_git(cls, pr: dict) -> "PullRequestResultState":
        """The state of an opened pull request, from the git provider's response."""
        if pr["merged_at"]:
            return cls.MERGED
        if pr["state"] == "closed":
            return cls.CLOSED
        return cls.OPENED
