from enum import Enum


class TriggerState(str, Enum):
    """
    The state of a trigger (a pull request or an API request), as nexus-api defines it.

    UNKNOWN: recorded, not yet evaluated.
    REJECTED: for us but invalid. Has a state_cause. Final.
    YIELDED: a Task was created from it.
    """

    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"
    YIELDED = "YIELDED"
