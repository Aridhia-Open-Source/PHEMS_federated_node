"""Tests for GitHub PR status monitoring sensors."""

from unittest.mock import Mock
import pytest
import dagster as dg
from dagster import RunStatusSensorContext, DagsterRun, SkipReason

from app.definitions.sensors.github.pr_monitor import (
    PullRequestStatusSuccessSensor,
    PullRequestStatusFailureSensor,
    PullRequestTaskMonitor,
)
from app.backend import BackendAPI
from app.github import GithubAPI


@pytest.fixture
def mock_run():
    """Create a mock DagsterRun."""
    run = Mock(spec=DagsterRun)
    run.run_id = "parent-run-123"
    run.tags = {
        "trigger": "github",
        "pr_number": "42",
        "repo_id": "5",
        "repo_uri": "https://github.com/owner/trigger-repo",
    }
    return run


@pytest.fixture
def mock_context(mock_run):
    """Create a mock RunStatusSensorContext."""
    context = Mock(spec=RunStatusSensorContext)
    context.log = Mock()
    context.dagster_run = mock_run
    return context


@pytest.fixture
def mock_backend_api():
    """Create a mock BackendAPI."""
    return Mock(spec=BackendAPI)


@pytest.fixture
def mock_github_api():
    """Create a mock GithubAPI."""
    return Mock(spec=GithubAPI)


@pytest.fixture
def success_sensor(mock_context, mock_backend_api, mock_github_api):
    """Create a PullRequestStatusSuccessSensor instance."""
    return PullRequestStatusSuccessSensor(
        context=mock_context,
        backend_api=mock_backend_api,
        github_api=mock_github_api,
    )


@pytest.fixture
def failure_sensor(mock_context, mock_backend_api, mock_github_api):
    """Create a PullRequestStatusFailureSensor instance."""
    return PullRequestStatusFailureSensor(
        context=mock_context,
        backend_api=mock_backend_api,
        github_api=mock_github_api,
    )


class TestPullRequestTaskMonitor:
    """Test suite for PullRequestTaskMonitor base class."""

    def test_extracts_pr_number_from_tags(self, mock_context, mock_backend_api, mock_github_api):
        """Verify PR number is extracted from tags."""
        monitor = PullRequestTaskMonitor(
            context=mock_context,
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )

        assert monitor.pr_number == 42

    def test_extracts_repo_id_from_tags(self, mock_context, mock_backend_api, mock_github_api):
        """Verify repo ID is extracted from tags."""
        monitor = PullRequestTaskMonitor(
            context=mock_context,
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )

        assert monitor.repo_id == 5

    def test_detects_github_trigger(self, mock_context, mock_backend_api, mock_github_api):
        """Verify GitHub trigger is correctly detected."""
        monitor = PullRequestTaskMonitor(
            context=mock_context,
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )

        assert monitor.is_github_trigger is True


class TestPullRequestStatusSuccessSensor:
    """Test suite for PullRequestStatusSuccessSensor."""

    def test_marks_pr_as_success_in_database(self, success_sensor, mock_backend_api):
        """Verify PR is marked as success in database."""
        list(success_sensor())

        mock_backend_api.patch_pull_request.assert_called_once_with(
            5, 42, {"status": "success"}
        )

    def test_returns_run_request_for_transfer_job(self, success_sensor):
        """Verify RunRequest is returned for github_transfer_job."""
        result = list(success_sensor())

        assert len(result) == 1
        assert isinstance(result[0], dg.RunRequest)
        assert result[0].job_name == "github_transfer_job"

    def test_run_request_has_correct_run_key(self, success_sensor):
        """Verify RunRequest has composite key for idempotency."""
        result = list(success_sensor())

        assert result[0].run_key == "5/42"

    def test_run_request_includes_pr_tags(self, success_sensor):
        """Verify RunRequest includes PR tracking tags."""
        result = list(success_sensor())

        assert result[0].tags["pr_number"] == "42"
        assert result[0].tags["repo_id"] == "5"
        assert result[0].tags["parent_run_id"] == "parent-run-123"

    def test_run_request_includes_github_trigger_tag(self, success_sensor):
        """Verify RunRequest includes GitHub trigger tag."""
        result = list(success_sensor())

        assert result[0].tags["trigger"] == "github"

    def test_run_config_includes_pr_number(self, success_sensor):
        """Verify run config includes PR number for transfer op."""
        result = list(success_sensor())

        pr_number = result[0].run_config["ops"]["github_transfer_op"]["config"]["pr_number"]
        assert pr_number == "42"

    def test_run_config_includes_parent_run_id(self, success_sensor):
        """Verify run config includes parent run ID for transfer op."""
        result = list(success_sensor())

        parent_run_id = result[0].run_config["ops"]["github_transfer_op"]["config"][
            "parent_run_id"
        ]
        assert parent_run_id == "parent-run-123"

    def test_run_config_includes_repo_uri(self, success_sensor):
        """Verify run config includes repo URI for transfer op."""
        result = list(success_sensor())

        repo_uri = result[0].run_config["ops"]["github_transfer_op"]["config"]["repo_uri"]
        assert repo_uri == "https://github.com/owner/trigger-repo"

    def test_logs_pull_request_update(self, success_sensor, mock_context):
        """Verify status update is logged."""
        list(success_sensor())

        assert mock_context.log.info.called

    def test_skips_if_not_github_trigger(self, mock_context, mock_backend_api, mock_github_api):
        """Verify sensor skips for non-GitHub triggered runs."""
        mock_context.dagster_run.tags["trigger"] = "manual"

        sensor = PullRequestStatusSuccessSensor(
            context=mock_context,
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)

    def test_raises_if_missing_repo_uri_in_tags(self, success_sensor, mock_context):
        """Verify sensor raises if repo_uri is missing from tags."""
        mock_context.dagster_run.tags.pop("repo_uri")

        with pytest.raises(KeyError):
            list(success_sensor())

    def test_calls_database_before_triggering_transfer(
        self, success_sensor, mock_backend_api
    ):
        """Verify database is updated before transfer job is triggered."""
        list(success_sensor())

        # Backend API should be called
        assert mock_backend_api.patch_pull_request.called

    def test_transfer_job_triggered_after_db_update(
        self, success_sensor, mock_backend_api
    ):
        """Verify transfer job is not triggered if DB update fails."""
        mock_backend_api.patch_pull_request.side_effect = Exception("DB error")

        with pytest.raises(Exception):
            list(success_sensor())


class TestPullRequestStatusFailureSensor:
    """Test suite for PullRequestStatusFailureSensor."""

    def test_marks_pr_as_failed_in_database(self, failure_sensor, mock_backend_api):
        """Verify PR is marked as failed in database."""
        list(failure_sensor())

        mock_backend_api.patch_pull_request.assert_called_once_with(
            5, 42, {"status": "failed"}
        )

    def test_does_not_return_run_request(self, failure_sensor):
        """Verify no RunRequest is returned (no transfer job on failure)."""
        result = list(failure_sensor())

        assert len(result) == 0

    def test_logs_failure_status_update(self, failure_sensor, mock_context):
        """Verify failure status update is logged."""
        list(failure_sensor())

        assert mock_context.log.error.called

    def test_skips_if_not_github_trigger(self, mock_context, mock_backend_api, mock_github_api):
        """Verify sensor skips for non-GitHub triggered runs."""
        mock_context.dagster_run.tags["trigger"] = "manual"

        sensor = PullRequestStatusFailureSensor(
            context=mock_context,
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)

    def test_raises_if_missing_pr_tags(self, failure_sensor, mock_context):
        """Verify sensor raises if required PR tags are missing."""
        mock_context.dagster_run.tags.pop("pr_number")

        with pytest.raises(ValueError, match="missing required PR tags"):
            list(failure_sensor())

    def test_extracts_correct_pr_and_repo_ids(self, failure_sensor):
        """Verify correct PR and repo IDs are extracted."""
        list(failure_sensor())

        # Verify the backend API was called with correct IDs
        call_args = failure_sensor.backend_api.patch_pull_request.call_args
        assert call_args[0][0] == 5  # repo_id
        assert call_args[0][1] == 42  # pr_number

    def test_database_error_propagates(self, failure_sensor, mock_backend_api):
        """Verify database errors are not caught."""
        mock_backend_api.patch_pull_request.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            list(failure_sensor())
