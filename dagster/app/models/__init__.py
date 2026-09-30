"""Wire models for the backend API responses this code location consumes."""

from app.models.audit import Audit
from app.models.dataset import Catalogue, Dataset, Dictionary
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestStatus
from app.models.registry import Registry
from app.models.request import Request
from app.models.task import Task
from app.models.task_status import TaskStatus
from app.models.task_request import TaskRequest
from app.models.trigger_repository import TriggerRepository
from app.models.whitelisted_image import WhitelistedImage

__all__ = [
    "Audit",
    "Catalogue",
    "Dataset",
    "Dictionary",
    "Project",
    "PullRequest",
    "PullRequestStatus",
    "Registry",
    "Request",
    "Task",
    "TaskStatus",
    "TaskRequest",
    "TriggerRepository",
    "WhitelistedImage",
]
