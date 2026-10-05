"""Trigger state enum."""

from enum import Enum


class TriggerState(str, Enum):
    """
    Where a trigger (a pull request or an API request) stands in its evaluation. A trigger is
    recorded first, then evaluated, and a Task is only created when evaluation succeeds.

    - UNKNOWN: recorded, not evaluated yet.
    - IGNORED: not for us, e.g. the pull request has no watched spec file. Needs a state_cause.
    - REJECTED: for us, but invalid, e.g. a bad spec. Needs a state_cause. The distinction from
      IGNORED is that a rejected trigger is something its author should be told about.
    - YIELDED: valid, and a Task was created from it.
    """

    UNKNOWN = "UNKNOWN"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"
    YIELDED = "YIELDED"

    def __str__(self):
        return self.value
