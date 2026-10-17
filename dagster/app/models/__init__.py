"""Wire models for the backend API responses this code location consumes."""

from app.models.dataset import Catalogue, Dataset, Dictionary, ProjectDataset
from app.models.git_provider import GitProvider
from app.models.project import Project
from app.models.pull_request import ChangedFile, NewPullRequest, PullRequest
from app.models.pull_request_result import PullRequestResult
from app.models.pull_request_result_step import PullRequestResultStep
from app.models.pull_request_trigger import PullRequestTrigger, TaskTrigger, TriggerRepositoryRef
from app.models.result_state import ResultState
from app.models.results_repository import ProjectResultsRepository, ResultsRepository
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.task import Task
from app.models.task_spec import TaskSpec
from app.models.task_status import TaskStatus
from app.models.trigger_state import TriggerState
from app.models.trigger_repository import ProjectTriggerRepository, TriggerRepository

__all__ = [
    "Catalogue",
    "ChangedFile",
    "Dataset",
    "Dictionary",
    "GitProvider",
    "NewPullRequest",
    "Project",
    "ProjectDataset",
    "ProjectResultsRepository",
    "ProjectTriggerRepository",
    "PullRequest",
    "PullRequestResult",
    "PullRequestResultStep",
    "PullRequestTrigger",
    "ResultState",
    "ResultsRepository",
    "Secret",
    "SecretProviderType",
    "Task",
    "TaskSpec",
    "TaskStatus",
    "TaskTrigger",
    "TriggerRepository",
    "TriggerRepositoryRef",
    "TriggerState",
]
