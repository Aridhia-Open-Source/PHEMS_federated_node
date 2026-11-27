"""Wire models for the backend API responses this code location consumes."""

from fednode.clients.nexus.models.dataset import Catalogue, Dataset, Dictionary, ProjectDataset
from fednode.clients.nexus.models.git_provider import GitProvider
from fednode.clients.nexus.models.git_token import GitToken
from fednode.clients.nexus.models.launch_decision import LaunchDecision
from fednode.clients.nexus.models.project import Project
from fednode.clients.nexus.models.pull_request import ChangedFile, NewPullRequest, PullRequest
from fednode.clients.nexus.models.pull_request_result import PullRequestResult
from fednode.clients.nexus.models.pull_request_result_step import PullRequestResultStep
from fednode.clients.nexus.models.pull_request_trigger import PullRequestTrigger, TaskTrigger, TriggerRepositoryRef
from fednode.clients.nexus.models.result_state import ResultState
from fednode.clients.nexus.models.run_record import RunNode, RunProject, RunRecord, RunResults, RunTask, RunTrigger
from fednode.clients.nexus.models.results_repository import ProjectResultsRepository, ResultsRepository
from fednode.clients.nexus.models.secret import Secret
from fednode.clients.nexus.models.secret_provider_type import SecretProviderType
from fednode.clients.nexus.models.task import Task
from fednode.clients.nexus.models.task_config import TaskConfig
from fednode.clients.nexus.models.task_resources import TaskResources
from fednode.clients.nexus.models.task_spec import TaskSpec
from fednode.clients.nexus.models.task_status import TaskStatus
from fednode.clients.nexus.models.trigger_state import TriggerState
from fednode.clients.nexus.models.trigger_repository import ProjectTriggerRepository, TriggerRepository

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
