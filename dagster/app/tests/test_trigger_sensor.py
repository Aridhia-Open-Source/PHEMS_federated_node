"""
Test suite for pull_request_trigger_sensor.

Tests the flow:
1. Fetch unprocessed valid PRs from database
2. Extract executors from PR spec
3. Yield RunRequest to github_task_monitor_job
4. Idempotency: same PR shouldn't trigger multiple runs
"""

import pytest
import requests
from unittest.mock import MagicMock, call
from dagster import build_sensor_context, SkipReason, RunRequest

from app.definitions.sensors.github.pr_trigger import PullRequestTriggerSensor
from app.tests.conftest import SAMPLE_REPO, SAMPLE_PR


class TestPullRequestTriggerSensor:
    """Tests for PullRequestTriggerSensor."""

    def test_skips_when_no_repositories(self):
        """Sensor should skip if no repositories are configured."""
        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = []

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)
        assert "No repositories" in str(result[0])

    def test_skips_when_no_unprocessed_prs(self):
        """Sensor should skip if all PRs are already processed."""
        repo = MagicMock()
        repo.id = SAMPLE_REPO["id"]

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo]
        mock_backend_api.get_pull_requests.return_value = []

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)
        assert "No unknown pull requests found" in str(result[0])

    def test_yields_run_requests_for_valid_and_unprocessed_prs(self):
        """Sensor should return list of RunRequests for unprocessed valid PRs."""
        from app.models import PullRequest
        import json

        repo = MagicMock()
        repo.id = SAMPLE_REPO["id"]
        repo.uri = SAMPLE_REPO["uri"]
        repo.path = SAMPLE_REPO["path"]
        repo.watch_dir = SAMPLE_REPO["watch_dir"]

        pr = MagicMock(spec=PullRequest)
        pr.number = SAMPLE_PR["number"]
        pr.title = SAMPLE_PR["title"]
        pr.repository_id = SAMPLE_REPO["id"]
        pr.spec = SAMPLE_PR["spec"]
        pr.merge_commit_sha = SAMPLE_PR["merge_commit_sha"]

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo]
        mock_backend_api.get_pull_requests.return_value = [pr]

        mock_github_api = MagicMock()
        # Mock PR files endpoint
        mock_github_api.get_pull_request_files.return_value = [
            {"filename": "specs/test.json", "status": "added"}
        ]
        # Mock file contents endpoint
        mock_github_api.get_file_contents.return_value = json.dumps({
            "spec": {
                "docker_image": "ghcr.io/org/experiment:latest",
                "env": {"KEY": "value"},
            }
        })

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], RunRequest)
        assert result[0].run_key == f"{repo.id}/{pr.number}"
        assert result[0].tags["pr_number"] == str(pr.number)
        assert result[0].tags["repo_id"] == str(repo.id)
        assert result[0].tags["trigger"] == "github"

    def test_continues_on_backend_api_error(self):
        """Sensor should continue processing other repos if one fails."""
        repo1 = MagicMock()
        repo1.id = 1

        repo2 = MagicMock()
        repo2.id = 2

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo1, repo2]
        # First repo raises HTTP error, second succeeds
        mock_backend_api.get_pull_requests.side_effect = [
            requests.HTTPError("500 Server Error"),
            []
        ]

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        # Should skip (no work found) and not crash
        assert len(result) == 1
        assert isinstance(result[0], SkipReason)

