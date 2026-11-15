"""Wire models for the backend API responses this code location consumes."""

from nexus_client.models.dataset import Catalogue, Dataset, Dictionary, ProjectDataset
from nexus_client.models.git_provider import GitProvider
from nexus_client.models.git_token import GitToken
from nexus_client.models.launch_decision import LaunchDecision
from nexus_client.models.project import Project
from nexus_client.models.pull_request import ChangedFile, NewPullRequest, PullRequest
from nexus_client.models.pull_request_result import PullRequestResult
from nexus_client.models.pull_request_result_step import PullRequestResultStep
from nexus_client.models.pull_request_trigger import PullRequestTrigger, TaskTrigger, TriggerRepositoryRef
from nexus_client.models.result_state import ResultState
from nexus_client.models.run_record import RunNode, RunProject, RunRecord, RunResults, RunTask, RunTrigger
from nexus_client.models.results_repository import ProjectResultsRepository, ResultsRepository
from nexus_client.models.secret import Secret
from nexus_client.models.secret_provider_type import SecretProviderType
from nexus_client.models.task import Task
from nexus_client.models.task_config import TaskConfig
from nexus_client.models.task_resources import TaskResources
from nexus_client.models.task_spec import TaskSpec
from nexus_client.models.task_status import TaskStatus
from nexus_client.models.trigger_state import TriggerState
from nexus_client.models.trigger_repository import ProjectTriggerRepository, TriggerRepository

__all__ = [
    "Catalogue",
    "ChangedFile",
    "Dataset",
    "Dictionary",
    "GitProvider",
    "GitToken",
    "LaunchDecision",
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
    "TaskConfig",
    "TaskResources",
    "TaskSpec",
    "TaskStatus",
    "TaskTrigger",
    "TriggerRepository",
    "TriggerRepositoryRef",
    "TriggerState",
]
