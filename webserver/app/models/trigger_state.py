"""Trigger state enum."""

from enum import Enum


class TriggerState(str, Enum):
    """
    The verdict on a trigger, the request to run a task (a pull request or an API request).
    A trigger is recorded first, then evaluated, and a Task is only created when evaluation
    succeeds.

    - UNKNOWN: recorded, not evaluated yet.
    - REJECTED: for us, but invalid, e.g. a bad spec. Needs a state_cause. Final. A pull request
      that is not for a project gets no trigger at all.
    - YIELDED: valid, and a Task was created from it.
    """

    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"
    YIELDED = "YIELDED"

    def __str__(self):
        return self.value


# The moves allowed from each state (ADR 0019 decision 10). REJECTED and YIELDED are final.
TRIGGER_MOVES = {
    TriggerState.UNKNOWN.value: {TriggerState.YIELDED.value, TriggerState.REJECTED.value},
    TriggerState.YIELDED.value: set(),
    TriggerState.REJECTED.value: set(),
}
