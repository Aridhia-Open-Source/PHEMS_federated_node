from enum import Enum


class PullRequestResultStep(str, Enum):
    """
    The furthest step the delivery of a task's results by pull request has reached, as
    nexus-api defines it. It only moves forward, and nexus-api rejects a move back.

    UNKNOWN: the result is recorded, nothing is delivered yet.
    PUSHED: the results are pushed to their branch.
    OPENED: the pull request from that branch is opened.
    MERGED: the pull request is merged into the results repository's default branch.
    CLOSED: the pull request is closed without merging.
    REVOKED: the project's results repository was revoked: never delivered, final.
    STALE: the task's configuration changed since the task was created: never delivered, final.
    """

    UNKNOWN = "UNKNOWN"
    PUSHED = "PUSHED"
    OPENED = "OPENED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    STALE = "STALE"

    @classmethod
    def from_git(cls, pr: dict) -> "PullRequestResultStep":
        """The step of an opened pull request, from the git provider's response."""
        if pr["merged_at"]:
            return cls.MERGED
        if pr["state"] == "closed":
            return cls.CLOSED
        return cls.OPENED
