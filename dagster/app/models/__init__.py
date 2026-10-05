"""Wire models for the backend API responses this code location consumes."""

from app.models.dataset import Catalogue, Dataset, Dictionary
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.pull_request_spec import PullRequestSpec
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.task import Task
from app.models.task_status import TaskStatus
from app.models.trigger_state import TriggerState
from app.models.trigger_repository import TriggerRepository

__all__ = [
    "Catalogue",
    "Dataset",
    "Dictionary",
    "Project",
    "PullRequest",
    "PullRequestSpec",
    "Secret",
    "SecretProviderType",
    "Task",
    "TaskStatus",
    "TriggerRepository",
    "TriggerState",
]
