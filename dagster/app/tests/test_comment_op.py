"""Tests for GitHub PR comment operation."""

from unittest.mock import Mock
import pytest
import dagster as dg
from dagster import RunStatusSensorContext

from app.definitions.sensors.github.comment_op import GithubCommentOperation
from app.github import GithubAPI


@pytest.fixture
def mock_context():
    """Create a mock OpExecutionContext."""
    context = Mock()
    context.log = Mock()
    context.op_config = {
        "pr_number": "42",
        "parent_run_id": "test-run-001",
        "repo_uri": "https://github.com/Aridhia-Open-Source/test-repo",
    }
    return context


@pytest.fixture
def mock_github_api():
    """Create a mock GithubAPI."""
    return Mock(spec=GithubAPI)


class TestGithubCommentOperation:
    """Test suite for GithubCommentOperation."""

    def test_adds_comment_to_pr(self, mock_context, mock_github_api):
        """Verify comment is added to PR."""
        operation = GithubCommentOperation(mock_context, mock_github_api)
        operation()

        mock_github_api.add_pull_request_comment.assert_called_once()
        call_args = mock_github_api.add_pull_request_comment.call_args
        assert "42" in str(call_args)  # pr_number
        assert "test-run-001" in str(call_args)  # parent_run_id

    def test_comment_contains_success_message(self, mock_context, mock_github_api):
        """Verify comment contains success indicator."""
        operation = GithubCommentOperation(mock_context, mock_github_api)
        operation()

        call_args = mock_github_api.add_pull_request_comment.call_args
        body = call_args[0][2]  # third arg is body
        assert "✅" in body or "Analysis complete" in body

    def test_comment_includes_run_id(self, mock_context, mock_github_api):
        """Verify comment includes parent run ID."""
        operation = GithubCommentOperation(mock_context, mock_github_api)
        operation()

        call_args = mock_github_api.add_pull_request_comment.call_args
        body = call_args[0][2]
        assert "test-run-001" in body

    def test_logs_comment_action(self, mock_context, mock_github_api):
        """Verify comment action is logged."""
        operation = GithubCommentOperation(mock_context, mock_github_api)
        operation()

        assert mock_context.log.info.called
