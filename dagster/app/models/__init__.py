"""Wire models for the backend API responses this code location consumes."""

from app.models.dataset import Catalogue, Dataset, Dictionary
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.merge_status import MergeStatus
from app.models.pull_request_spec import PullRequestSpec
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.task import Task
from app.models.task_result import TaskResult
from app.models.task_result_status import TaskResultStatus
from app.models.task_status import TaskStatus
from app.models.trigger_state import TriggerState
from app.models.trigger_repository import TriggerRepository

__all__ = [
    "Catalogue",
    "Dataset",
    "Dictionary",
    "Project",
    "PullRequest",
    "MergeStatus",
    "PullRequestSpec",
    "ResultsRepository",
    "Secret",
    "SecretProviderType",
    "Task",
    "TaskResult",
    "TaskResultStatus",
    "TaskStatus",
    "TriggerRepository",
    "TriggerState",
]
