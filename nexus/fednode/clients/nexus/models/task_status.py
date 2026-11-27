from enum import Enum


class TaskStatus(str, Enum):
    """The canonical task status, as nexus-api defines it."""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
