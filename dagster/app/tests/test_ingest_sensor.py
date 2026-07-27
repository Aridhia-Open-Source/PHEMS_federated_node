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
        repo.pull_request_cursor = "2026-01-01T00:00:00Z"

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

    def test_resolve_dataset_id_from_spec_uses_spec_dataset(self):
        """Should use dataset name from spec if provided."""
        repo = MagicMock()
        repo.default_dataset_id = 10

        spec = {"dataset": "my-dataset"}

        mock_dataset = MagicMock()
        mock_dataset.id = 20

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=MagicMock(),
            github_api=MagicMock(),
        )
        sensor.backend_api.get_dataset_by_name.return_value = mock_dataset

        result = sensor._resolve_dataset_id_from_spec(repo, spec)

        assert result == 20
        sensor.backend_api.get_dataset_by_name.assert_called_once_with("my-dataset")

    def test_resolve_dataset_id_from_spec_uses_default(self):
        """Should fall back to repo default if no dataset in spec."""
        repo = MagicMock()
        repo.default_dataset_id = 10

        spec = {}

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=MagicMock(),
            github_api=MagicMock(),
        )

        result = sensor._resolve_dataset_id_from_spec(repo, spec)

        assert result == 10

    def test_resolve_dataset_id_from_spec_dataset_not_found(self):
        """Should fall back to default if dataset name not found."""
        repo = MagicMock()
        repo.default_dataset_id = 10

        spec = {"dataset": "nonexistent"}

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=MagicMock(),
            github_api=MagicMock(),
        )
        sensor.backend_api.get_dataset_by_name.return_value = None

        result = sensor._resolve_dataset_id_from_spec(repo, spec)

        assert result == 10

    def test_save_prs_batch_chunks_at_100(self):
        """Should split PRs into batches of 100 before sending."""
        repo = MagicMock()
        repo.id = 1

        prs = [
            MagicMock(spec=PullRequest)
            for _ in range(250)
        ]
        for i, pr in enumerate(prs):
            pr.model_dump.return_value = {"number": i + 1}

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=MagicMock(),
            github_api=MagicMock(),
        )
        sensor.backend_api.create_pull_requests_batch.return_value = None

        result = sensor._save_prs_batch(repo, prs)

        # Should make 3 calls: 100, 100, 50
        assert sensor.backend_api.create_pull_requests_batch.call_count == 3
        calls = sensor.backend_api.create_pull_requests_batch.call_args_list
        assert len(calls[0][0][1]) == 100  # First batch
        assert len(calls[1][0][1]) == 100  # Second batch
        assert len(calls[2][0][1]) == 50   # Third batch

    def test_save_prs_batch_returns_dicts(self):
        """Should return list of PR dicts."""
        repo = MagicMock()
        repo.id = 1

        prs = [MagicMock(spec=PullRequest) for _ in range(2)]
        prs[0].model_dump.return_value = {"number": 1}
        prs[1].model_dump.return_value = {"number": 2}

        sensor = PullRequestIngestSensor(
            context=MagicMock(),
            backend_api=MagicMock(),
            github_api=MagicMock(),
        )

        result = sensor._save_prs_batch(repo, prs)

        assert len(result) == 2
        assert result[0] == {"number": 1}
        assert result[1] == {"number": 2}
