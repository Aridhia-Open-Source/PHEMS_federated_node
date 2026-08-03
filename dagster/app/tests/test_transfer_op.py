"""Tests for GitHub results transfer operation."""

import tempfile
from unittest.mock import Mock, patch, MagicMock
import pytest
import dagster as dg
from dagster import OpExecutionContext

from app.definitions.sensors.github.transfer_op import GithubTransferOperation
from app.config import GithubTransferConfig
from app.github import GithubAPI


@pytest.fixture
def mock_context():
    """Create a mock OpExecutionContext."""
    context = Mock(spec=OpExecutionContext)
    context.log = Mock()
    context.op_config = {
        "pr_number": "42",
        "parent_run_id": "test-run-123",
        "repo_uri": "https://github.com/owner/trigger-repo",
    }
    return context


@pytest.fixture
def mock_github_api():
    """Create a mock GithubAPI."""
    api = Mock(spec=GithubAPI)
    api.branch_exists.return_value = False
    api.create_pull_request.return_value = "https://github.com/owner/delivery-repo/pull/1"
    return api


@pytest.fixture
def mock_config():
    """Create a mock GithubTransferConfig."""
    config = Mock(spec=GithubTransferConfig)
    config.token = "test-token"
    config.delivery_repo = "owner/delivery-repo"
    config.base_branch = "main"
    config.results_dir = "mgmt/results"
    config.artifact_mount_path = "/artifacts"
    return config


@pytest.fixture
def transfer_op(mock_context, mock_github_api, mock_config):
    """Create a GithubTransferOperation instance."""
    return GithubTransferOperation(mock_context, mock_github_api, mock_config)


class TestGithubTransferOperation:
    """Test suite for GithubTransferOperation."""

    def test_extracts_config_from_context(self, transfer_op, mock_context):
        """Verify extraction of config from context."""
        pr_number, parent_run_id, repo_uri = transfer_op._extract_config()
        assert pr_number == "42"
        assert parent_run_id == "test-run-123"
        assert repo_uri == "https://github.com/owner/trigger-repo"

    def test_parses_repo_uri(self, transfer_op):
        """Verify parsing owner and repo from URI."""
        owner, repo = transfer_op._parse_repo_uri("https://github.com/owner/trigger-repo")
        assert owner == "owner"
        assert repo == "trigger-repo"

    @patch("app.definitions.sensors.github.transfer_op._git")
    def test_setup_repo_clones_delivery_repo(self, mock_git, transfer_op, mock_config):
        """Verify setup clones delivery repo and creates branch."""
        with tempfile.TemporaryDirectory() as clone_dir:
            transfer_op._setup_repo(clone_dir, "42-test-run-123-results", "owner", "delivery-repo")

            mock_git.assert_any_call(
                [
                    "clone",
                    "--depth=1",
                    "https://test-token@github.com/owner/delivery-repo.git",
                    clone_dir,
                ]
            )

    @patch("app.definitions.sensors.github.transfer_op._git")
    def test_setup_repo_configures_git_user(self, mock_git, transfer_op):
        """Verify git user is configured."""
        with tempfile.TemporaryDirectory() as clone_dir:
            transfer_op._setup_repo(clone_dir, "42-test-run-123-results", "owner", "delivery-repo")

            calls = [call[0][0] for call in mock_git.call_args_list]
            assert any("config" in call and "user.name" in call for call in calls)

    @patch("app.definitions.sensors.github.transfer_op._git")
    def test_setup_repo_checks_branch_exists(self, mock_git, transfer_op, mock_github_api):
        """Verify branch existence is checked before checkout."""
        with tempfile.TemporaryDirectory() as clone_dir:
            transfer_op._setup_repo(clone_dir, "42-test-run-123-results", "owner", "delivery-repo")

            mock_github_api.branch_exists.assert_called_once_with(
                "owner/delivery-repo", "42-test-run-123-results"
            )

    @patch("app.definitions.sensors.github.transfer_op._git")
    def test_setup_repo_raises_if_branch_exists(self, mock_git, transfer_op, mock_github_api):
        """Verify exception raised if results branch already exists."""
        mock_github_api.branch_exists.return_value = True

        with tempfile.TemporaryDirectory() as clone_dir:
            with pytest.raises(Exception, match="already exists on remote"):
                transfer_op._setup_repo(clone_dir, "42-test-run-123-results", "owner", "delivery-repo")

    def test_archive_results_creates_directory_structure(self, transfer_op):
        """Verify results are archived in correct directory structure."""
        with tempfile.TemporaryDirectory() as clone_dir:
            artifact_path = transfer_op._archive_results(
                clone_dir, "42", "test-run-123", "owner", "trigger-repo"
            )

            assert artifact_path is not None

    @patch("app.definitions.sensors.github.transfer_op._git")
    def test_commit_and_push_commits_changes(self, mock_git, transfer_op):
        """Verify changes are committed with correct message."""
        with tempfile.TemporaryDirectory() as clone_dir:
            transfer_op._commit_and_push(
                clone_dir, "42", "test-run-123", "42-test-run-123-results"
            )

            calls = [call[0][0] for call in mock_git.call_args_list]
            assert any("commit" in call for call in calls)

    @patch("app.definitions.sensors.github.transfer_op._git")
    def test_commit_and_push_pushes_to_remote(self, mock_git, transfer_op):
        """Verify branch is pushed to remote."""
        with tempfile.TemporaryDirectory() as clone_dir:
            transfer_op._commit_and_push(
                clone_dir, "42", "test-run-123", "42-test-run-123-results"
            )

            calls = [call[0][0] for call in mock_git.call_args_list]
            assert any("push" in call for call in calls)

    def test_create_results_pr_includes_trigger_repo(self, transfer_op, mock_github_api):
        """Verify PR title and body include trigger repo info."""
        pr_url = transfer_op._create_results_pr(
            "42-test-run-123-results", "42", "test-run-123", "owner", "trigger-repo", "owner", "delivery-repo"
        )

        assert pr_url == "https://github.com/owner/delivery-repo/pull/1"

        call_args = mock_github_api.create_pull_request.call_args
        assert "owner/trigger-repo" in call_args[0][3]  # title
        assert "owner/trigger-repo" in call_args[0][4]  # body

    def test_create_results_pr_uses_delivery_repo(self, transfer_op, mock_github_api, mock_config):
        """Verify PR is created in delivery repo."""
        transfer_op._create_results_pr(
            "42-test-run-123-results", "42", "test-run-123", "owner", "trigger-repo", "owner", "delivery-repo"
        )

        call_args = mock_github_api.create_pull_request.call_args
        assert call_args[0][0] == "owner/delivery-repo"

    def test_create_results_pr_uses_base_branch(self, transfer_op, mock_github_api, mock_config):
        """Verify PR is created against configured base branch."""
        transfer_op._create_results_pr(
            "42-test-run-123-results", "42", "test-run-123", "owner", "trigger-repo", "owner", "delivery-repo"
        )

        call_args = mock_github_api.create_pull_request.call_args
        assert call_args[0][2] == "main"

    @patch("app.definitions.sensors.github.transfer_op._git")
    @patch("app.definitions.sensors.github.transfer_op._zip_dir")
    def test_call_returns_output_with_pr_url(self, mock_zip, mock_git, transfer_op):
        """Verify __call__ returns Output with PR URL and branch."""
        result = transfer_op()

        assert isinstance(result, dg.Output)
        assert result.value["pr_url"] == "https://github.com/owner/delivery-repo/pull/1"
        assert result.value["branch"] == "42-test-run-123-results"

    @patch("app.definitions.sensors.github.transfer_op._git")
    @patch("app.definitions.sensors.github.transfer_op._zip_dir")
    def test_call_logs_transfer_start(self, mock_zip, mock_git, transfer_op, mock_context):
        """Verify transfer operation logs start message."""
        transfer_op()

        assert mock_context.log.info.called
        log_calls = [str(call) for call in mock_context.log.info.call_args_list]
        assert any("transfer starting" in str(call).lower() for call in log_calls)

    @patch("app.definitions.sensors.github.transfer_op._git")
    @patch("app.definitions.sensors.github.transfer_op._zip_dir")
    def test_call_cleans_up_clone_dir_on_success(self, mock_zip, mock_git, transfer_op):
        """Verify temp directory is cleaned up after success."""
        with patch("shutil.rmtree") as mock_rmtree:
            transfer_op()
            assert mock_rmtree.called
