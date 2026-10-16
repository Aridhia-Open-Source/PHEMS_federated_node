"""
The backend API responses the webserver's contract tests (webserver/tests/test_api_contract.py)
write to JSON, parsed into the models this code location reads them with. The files are copied
here by scripts/sync_contract_fixtures.sh, because the test image only contains dagster/.
"""
import json
from pathlib import Path

import pytest

from app.models import (
    Dataset, Project, ProjectDataset, ProjectResultsRepository, PullRequestResult, PullRequestTrigger,
    ResultsRepository, Secret, Task, TriggerRepository,
)

CONTRACTS_DIR = Path(__file__).parent / "contracts"


def load(name: str):
    return json.loads((CONTRACTS_DIR / f"{name}.json").read_text())


def items_of(name: str) -> list[dict]:
    body = load(name)
    return body["items"] if isinstance(body, dict) and "items" in body else body


@pytest.mark.parametrize("name, model", [
    ("trigger_repositories_list", TriggerRepository),
    ("results_repositories", ResultsRepository),
    ("project_results_repositories", ProjectResultsRepository),
    ("datasets_page", Dataset),
    ("project_datasets", ProjectDataset),
    ("projects_page", Project),
    ("pull_requests_batch", PullRequestTrigger),
    ("pull_requests_page", PullRequestTrigger),
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
    task = Task(**load("task_api"))

    assert task.spec.dataset_id == 1
    assert Task(**load("pull_request_task")).spec.dataset_id == 1


def test_trigger_repository_values():
    repository = TriggerRepository(**load("trigger_repository"))

    assert repository.pr_cursor == "2026-01-01T00:00:00Z"
    assert repository.secret.label == "test-creds"
    assert repository.repo_path == "org/test-repo"


def test_a_global_secret_parses():
    """A global secret has no project: Dagster reads only key, namespace and provider."""
    secret = load("secret")

    assert "project_id" not in secret
    Secret(**secret)


def test_a_results_repository_assignment_nests_the_global_repository():
    [assignment] = items_of("project_results_repositories")
    parsed = ProjectResultsRepository(**assignment)

    assert parsed.results_repository.repo_path == "org/results"
    assert (parsed.target_dir, parsed.active) == ("results", True)
    assert "project_id" not in assignment["results_repository"]
