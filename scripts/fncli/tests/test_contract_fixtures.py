"""
The backend API responses the webserver's contract tests (webserver/tests/test_api_contract.py)
write to JSON, parsed into the models fncli reads them with. The files are read from the
webserver's tests, where they are written.
"""
import json
from pathlib import Path

import pytest

from fncli.dagster.models import (
    Dataset, Project, ProjectDataset, ProjectResultsRepository, ProjectTriggerRepository, PullRequestResult,
    PullRequest, PullRequestTrigger, ResultsRepository, Secret, Task, TriggerRepository,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "webserver" / "tests" / "contracts"


def load(name: str):
    return json.loads((CONTRACTS_DIR / f"{name}.json").read_text())


def items_of(name: str) -> list[dict]:
    body = load(name)
    return body["items"] if isinstance(body, dict) and "items" in body else body


@pytest.mark.parametrize("name, model", [
    ("trigger_repositories_list", TriggerRepository),
    ("project_trigger_repositories", ProjectTriggerRepository),
    ("project_trigger_repositories_active", ProjectTriggerRepository),
    ("results_repositories", ResultsRepository),
    ("project_results_repositories", ProjectResultsRepository),
    ("datasets_page", Dataset),
    ("project_datasets", ProjectDataset),
    ("projects_page", Project),
    ("pull_requests_batch", PullRequestTrigger),
    ("pull_requests_page", PullRequestTrigger),
    ("repository_pull_requests_page", PullRequest),
    ("results_by_step", PullRequestResult),
    ("secrets_list", Secret),
])
def test_lists_parse(name, model):
    items = items_of(name)
    assert items
    for item in items:
        model(**item)


@pytest.mark.parametrize("name, model", [
    ("trigger_repository", TriggerRepository),
    ("results_repository", ResultsRepository),
    ("dataset", Dataset),
    ("project", Project),
    ("pull_request", PullRequestTrigger),
    ("pull_request_ignored", PullRequestTrigger),
    ("pull_request_task", Task),
    ("task_api", Task),
    ("result_created", PullRequestResult),
    ("result_opened", PullRequestResult),
    ("secret", Secret),
])
def test_single_parses(name, model):
    model(**load(name))


def test_task_spec_has_the_dataset_id():
    assert Task(**load("task_api")).spec.dataset_id == 1
    assert Task(**load("pull_request_task")).spec.dataset_id == 1


def test_a_global_secret_parses():
    """A global secret has no project: fncli reads only key, namespace and provider."""
    secret = load("secret")

    assert "project_id" not in secret
    Secret(**secret)
