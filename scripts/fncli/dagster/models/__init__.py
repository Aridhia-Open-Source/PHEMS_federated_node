"""Wire models for the backend API responses this code location consumes."""

from fncli.dagster.models.dataset import Catalogue, Dataset, Dictionary, ProjectDataset
from fncli.dagster.models.project import Project
from fncli.dagster.models.pull_request_result import PullRequestResult
from fncli.dagster.models.pull_request_trigger import PullRequestTrigger
from fncli.dagster.models.results_repository import ProjectResultsRepository, ResultsRepository
from fncli.dagster.models.secret import Secret
from fncli.dagster.models.secret_provider_type import SecretProviderType
from fncli.dagster.models.task import Task
from fncli.dagster.models.task_spec import TaskSpec
from fncli.dagster.models.trigger_repository import TriggerRepository
from fncli.dagster.models.trigger_state import TriggerState

__all__ = [
    "Catalogue",
    "Dataset",
    "Dictionary",
    "Project",
    "ProjectDataset",
    "PullRequestResult",
    "PullRequestTrigger",
    "ProjectResultsRepository",
    "ResultsRepository",
    "Secret",
    "SecretProviderType",
    "Task",
    "TaskSpec",
    "TriggerRepository",
    "TriggerState",
]
