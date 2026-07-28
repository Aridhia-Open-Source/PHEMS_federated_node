import json
import pytest
from unittest.mock import Mock, MagicMock
from dagster import DagsterInstance, build_sensor_context
from dagster._core.storage.dagster_run import DagsterRun
from dagster._core.events import DagsterEvent, DagsterEventType


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_REPO = {
    "id": 1,
    "uri": "github.com/org/repo",
    "path": "org/repo",
    "base_branch": "main",
    "watch_dir": "specs/",
}

SAMPLE_REPOSITORY_OBJ = {
    "id": 1,
    "uri": "github.com/org/repo",
    "path": "org/repo",
    "base_branch": "main",
    "watch_dir": "specs/",
    "initial_cursor": "2026-01-01T00:00:00Z",
    "pull_requests": [],
}

SAMPLE_PR = {
    "repository_id": 1,
    "number": 5,
    "title": "Add experiment spec",
    "raised_by": "developer",
    "merged_at": "2026-06-26T10:00:00Z",
    "merge_commit_sha": "abc123def456",
    "saved_at": "2026-06-26T10:05:00Z",
    "status": "unprocessed",
    "spec": {
        "docker_image": "ghcr.io/org/experiment:latest",
        "env": {"KEY": "value"},
    },
}

SAMPLE_INVALID_PR = {
    "repository_id": 1,
    "number": 6,
    "title": "Invalid spec",
    "raised_by": "developer",
    "merged_at": "2026-06-27T10:00:00Z",
    "merge_commit_sha": "xyz789abc123",
    "saved_at": "2026-06-27T10:05:00Z",
    "status": "unprocessed",
    "spec": {},
}

SAMPLE_IN_PROGRESS_PR = {
    "repository_id": 1,
    "number": 7,
    "title": "Currently processing",
    "raised_by": "developer",
    "merged_at": "2026-06-28T10:00:00Z",
    "merge_commit_sha": "pqr456xyz789",
    "saved_at": "2026-06-28T10:05:00Z",
    "status": "in_progress",
    "spec": {
        "docker_image": "ghcr.io/org/experiment:v2",
        "env": {"KEY": "value2"},
    },
}


# ---------------------------------------------------------------------------
# Dagster instance (shared across sensor tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def dagster_instance():
    return DagsterInstance.ephemeral()


# ---------------------------------------------------------------------------
# Sensor context helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sensor_context():
    """Build a sensor context with mocked resources."""
    context = build_sensor_context()
    context.resources.backend_api = MagicMock()
    context.resources.github_api = MagicMock()
    return context


# ---------------------------------------------------------------------------
# Webserver API mock helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_repos():
    return [SAMPLE_REPO]


def make_response(body, status_code=200):
    """Create a mock HTTP response."""
    mock = Mock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.raise_for_status = Mock()
    return mock


@pytest.fixture
def webserver_repos_response(mock_repos):
    return make_response(mock_repos)


# ---------------------------------------------------------------------------
# Backend API mock helpers
# ---------------------------------------------------------------------------

def make_backend_api_mock():
    """Create a fully mocked BackendAPI instance."""
    api = MagicMock()
    return api


@pytest.fixture
def mock_backend_api():
    return make_backend_api_mock()


# ---------------------------------------------------------------------------
# GitHub API mock helpers
# ---------------------------------------------------------------------------

def make_github_api_mock():
    """Create a fully mocked GithubAPI instance."""
    api = MagicMock()
    return api


@pytest.fixture
def mock_github_api():
    return make_github_api_mock()


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
    return json.dumps(SAMPLE_PR["spec"])


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
