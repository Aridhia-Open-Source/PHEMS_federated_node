"""nexus-api payloads and a response mock for the client tests (Dagster's app/tests/conftest.py has its own copies)."""
from unittest.mock import Mock

SAMPLE_SECRET = {
    "id": 3,
    "project_id": 1,
    "label": "git-token",
    "description": None,
    "provider": "K8S",
    "key": "git-token-abc",
    "enabled": True,
    "namespace": "fn",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}

SAMPLE_DATASET = {
    "id": 1,
    "secret": SAMPLE_SECRET,
    "name": "cdm",
    "host": "db.host",
    "port": 5432,
    "read_schema": "cdm",
    "write_schema": "results",
    "type": "postgres",
    "extra_connection_args": None,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "enabled": True,
    "slug": "cdm",
    "url": "https://db.host/cdm",
}

SAMPLE_PROVIDER = {
    "id": 1,
    "name": "github-github.com",
    "type": "github",
    "uri": "https://github.com",
    "api_uri": "https://api.github.com",
    "enabled": True,
}

SAMPLE_TRIGGER_REPOSITORY = {
    "id": 1,
    "uri": "https://github.com/org/repo",
    "repo_path": "org/repo",
    "provider": SAMPLE_PROVIDER,
    "secret": SAMPLE_SECRET,
    "enabled": True,
    "pr_cursor": "2026-01-01T00:00:00Z",
}

SAMPLE_REPO = {
    "id": 1,
    "project_id": 1,
    "trigger_repository": SAMPLE_TRIGGER_REPOSITORY,
    "base_branch": "main",
    "watch_dir": "specs/",
    "dataset_id": 1,
    "pr_cursor": "2026-01-01T00:00:00Z",
    "enabled": True,
    "revoked": False,
    "active": True,
}

SAMPLE_REPOSITORY_OBJ = {
    **SAMPLE_REPO,
    "initial_cursor": "2026-01-01T00:00:00Z",
    "pull_requests": [],
}

SAMPLE_PR = {
    "project_id": 1,
    "trigger_repository_id": 1,
    "number": 5,
    "title": "Add experiment spec",
    "raised_by": "developer",
    "merged_at": "2026-06-26T10:00:00Z",
    "merge_commit_sha": "abc123def456",
    "state": "UNKNOWN",
    "spec_files": [],
}


def make_response(body, status_code=200):
    """Create a mock HTTP response."""
    mock = Mock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.raise_for_status = Mock()
    return mock
