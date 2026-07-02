import json
import pytest
from unittest.mock import Mock
from dagster import DagsterInstance
from dagster._core.storage.dagster_run import DagsterRun
from dagster._core.events import DagsterEvent, DagsterEventType


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_REPO = {
    "id": 1,
    "uri": "github.com/org/repo",
    "base_branch": "main",
    "pr_cursor": 0,
    "polled_at": None,
}

SAMPLE_PR = {
    "number": 5,
    "merged_at": "2026-06-26T10:00:00Z",
    "merge_commit_sha": "abc123",
    "watched_files": ["requests/experiment.json"],
}

SAMPLE_SPEC = {
    "spec": {
        "docker_image": "ghcr.io/org/experiment:latest",
        "args": {"KEY": "value"},
        "tags": {"request_name": "request_001"},
    }
}


# ---------------------------------------------------------------------------
# Dagster instance (shared across sensor tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def dagster_instance():
    return DagsterInstance.ephemeral()


# ---------------------------------------------------------------------------
# Webserver API mock helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_repos():
    return [SAMPLE_REPO]


def make_response(body, status_code=200):
    mock = Mock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.raise_for_status = Mock()
    return mock


@pytest.fixture
def webserver_repos_response(mock_repos):
    return make_response(mock_repos)


# ---------------------------------------------------------------------------
# GitHub API mock helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pr():
    return dict(SAMPLE_PR)


@pytest.fixture
def mock_pr_files():
    return [
        {"filename": "requests/experiment.json", "status": "added"},
    ]


@pytest.fixture
def mock_spec_content():
    return json.dumps(SAMPLE_SPEC)


def make_github_search_response(prs):
    return make_response({"items": [{"number": pr["number"]} for pr in prs]})


# ---------------------------------------------------------------------------
# Dagster run fixtures (for run_status_sensor tests)
# ---------------------------------------------------------------------------

def make_dagster_run(tags: dict, run_id: str = "test-run-id", job_name: str = "k8s_pipes_job"):
    return DagsterRun(run_id=run_id, job_name=job_name, tags=tags)


def make_success_event(job_name: str = "k8s_pipes_job"):
    return DagsterEvent(
        event_type_value=DagsterEventType.RUN_SUCCESS.value,
        job_name=job_name,
    )


@pytest.fixture
def github_triggered_run():
    return make_dagster_run(tags={
        "trigger": "github",
        "pr_number": "5",
        "repo_id": "1",
        "repo_uri": "github.com/org/repo",
    })


@pytest.fixture
def non_github_run():
    return make_dagster_run(tags={"trigger": "manual"})


@pytest.fixture
def transfer_completed_run():
    return make_dagster_run(
        run_id="transfer-run-id",
        job_name="github_transfer_job",
        tags={
            "trigger": "github_transfer",
            "pr_number": "5",
            "repo_id": "1",
            "repo_uri": "github.com/org/repo",
            "parent_run_id": "test-run-id",
        },
    )


@pytest.fixture
def success_event():
    return make_success_event()
