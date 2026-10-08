"""Wire models for the backend API responses this code location consumes."""

from app.models.dataset import Catalogue, Dataset, Dictionary
from app.models.project import Project
from app.models.pull_request_result import PullRequestResult
from app.models.pull_request_result_state import PullRequestResultState
from app.models.pull_request_spec import PullRequestSpec
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.results_repository import ResultsRepository
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
    "PullRequestResult",
    "PullRequestResultState",
    "PullRequestSpec",
    "PullRequestTrigger",
    "ResultsRepository",
    "Secret",
    "SecretProviderType",
    "Task",
    "TaskStatus",
    "TriggerRepository",
    "TriggerState",
]
