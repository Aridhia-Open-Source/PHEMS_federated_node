"""
Test suite for pull_request_ingest_sensor.

Tests the flow:
1. Fetch merged PRs from GitHub
2. Extract spec, resolve dataset_id
3. Save PRs to database in batches (up to 100 per call)
"""

import json
import pytest
from unittest.mock import MagicMock, call
from dagster import SkipReason

from app.definitions.sensors.github.pr_ingest import PullRequestIngestSensor
from app.models import PullRequest, PullRequestStatus
from app.tests.conftest import SAMPLE_REPO, SAMPLE_PR


class TestPullRequestIngestSensor:
    """Tests for PullRequestIngestSensor."""

    def test_skips_when_no_repositories(self):
        """Sensor should skip if no repositories are configured."""
        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = []

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)
        assert "No repositories" in str(result[0])

    def test_skips_when_no_new_prs(self):
        """Sensor should skip if no new PRs are found."""
        repo = MagicMock()
        repo.id = SAMPLE_REPO["id"]
        repo.path = SAMPLE_REPO["path"]
        repo.base_branch = SAMPLE_REPO["base_branch"]
        repo.pr_cursor = "2026-01-01T00:00:00Z"

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo]

        mock_github_api = MagicMock()
        mock_github_api.get_new_merged_pulls.return_value = []

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)
        assert "No new pull requests" in str(result[0])

