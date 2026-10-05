from enum import Enum


class TriggerState(str, Enum):
    """
    The state of a trigger (a pull request or an API request), as the webserver defines it.

    UNKNOWN: recorded, not yet evaluated.
    IGNORED: not for us (e.g. no watched spec file). Has a state_cause.
    REJECTED: for us but invalid. Has a state_cause.
    YIELDED: a Task was created from it.
    """

    UNKNOWN = "UNKNOWN"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"
    YIELDED = "YIELDED"
