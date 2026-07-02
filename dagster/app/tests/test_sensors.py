"""
Sensor tests.

Polling sensor (github_pull_request_polling_sensor):
  - calls GET /repositories on the webserver
  - for each repo, calls GithubClient.get_merged_prs_after_number
  - yields one RunRequest per new PR with repo_id/repo_uri/pr_number tags
  - PATCHes the webserver with the new pr_cursor + polled_at after finding PRs
  - skips repos with no new PRs

Run-status sensors (github_run_success_transfer_sensor, github_transfer_success_sensor):
  - forward tags from the triggering run into the next RunRequest
  - skip if required tags are missing
"""
import pytest
from unittest.mock import patch, Mock
from dagster import build_sensor_context, build_run_status_sensor_context, SkipReason, RunRequest

from app.definitions.sensors import (
    github_pull_request_polling_sensor,
    github_run_success_transfer_sensor,
    github_transfer_success_sensor,
)
from app.tests.conftest import make_response, make_dagster_run, make_success_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_sensor(sensor_fn, context):
    """Invoke a sensor and collect all yielded values into a list."""
    return list(sensor_fn(context))


# ---------------------------------------------------------------------------
# github_pull_request_polling_sensor
# ---------------------------------------------------------------------------

class TestPollingSeensor:
    def _context(self):
        return build_sensor_context()

    def test_skips_when_no_repos(self, mocker):
        mocker.patch("app.definitions.sensors.requests.get", return_value=make_response([]))
        results = collect_sensor(github_pull_request_polling_sensor, self._context())
        assert all(isinstance(r, SkipReason) for r in results)

    def test_skips_repo_with_no_new_prs(self, mocker, mock_repos, mock_pr, mock_spec_content):
        mocker.patch("app.definitions.sensors.requests.get", return_value=make_response(mock_repos))
        mocker.patch(
            "app.definitions.sensors.GithubAPI.get_merged_prs_after_number",
            return_value=[],
        )
        results = collect_sensor(github_pull_request_polling_sensor, self._context())
        assert all(isinstance(r, SkipReason) for r in results)

    def test_yields_run_request_for_new_pr(self, mocker, mock_repos, mock_pr, mock_spec_content):
        mocker.patch("app.definitions.sensors.requests.get", return_value=make_response(mock_repos))
        mocker.patch(
            "app.definitions.sensors.GithubAPI.get_merged_prs_after_number",
            return_value=[mock_pr],
        )
        mocker.patch(
            "app.definitions.sensors.GithubAPI.get_file_contents",
            return_value=mock_spec_content,
        )
        mocker.patch("app.definitions.sensors.requests.patch", return_value=make_response({}))

        results = collect_sensor(github_pull_request_polling_sensor, self._context())

        run_requests = [r for r in results if isinstance(r, RunRequest)]
        assert len(run_requests) == 1
        assert run_requests[0].tags["pr_number"] == str(mock_pr["number"])
        assert run_requests[0].tags["repo_id"] == str(mock_repos[0]["id"])
        assert run_requests[0].tags["repo_uri"] == mock_repos[0]["uri"]
        assert run_requests[0].tags["trigger"] == "github"
        # k8s_pipes_op config is built from spec["docker_image"] and spec["args"]
        op_config = run_requests[0].run_config["ops"]["k8s_pipes_op"]["config"]
        assert op_config["docker_image"] == "ghcr.io/org/experiment:latest"
        assert op_config["env"] == {"KEY": "value"}

    def test_updates_pr_cursor_after_finding_prs(self, mocker, mock_repos, mock_pr, mock_spec_content):
        mocker.patch("app.definitions.sensors.requests.get", return_value=make_response(mock_repos))
        mocker.patch(
            "app.definitions.sensors.GithubAPI.get_merged_prs_after_number",
            return_value=[mock_pr],
        )
        mocker.patch("app.definitions.sensors.GithubAPI.get_file_contents", return_value=mock_spec_content)
        patch_mock = mocker.patch("app.definitions.sensors.requests.patch", return_value=make_response({}))

        collect_sensor(github_pull_request_polling_sensor, self._context())

        patch_mock.assert_called_once()
        call_kwargs = patch_mock.call_args
        assert call_kwargs[1]["json"]["pr_cursor"] == mock_pr["number"]
        assert "polled_at" in call_kwargs[1]["json"]

    def test_does_not_patch_when_no_new_prs(self, mocker, mock_repos):
        mocker.patch("app.definitions.sensors.requests.get", return_value=make_response(mock_repos))
        mocker.patch(
            "app.definitions.sensors.GithubAPI.get_merged_prs_after_number",
            return_value=[],
        )
        patch_mock = mocker.patch("app.definitions.sensors.requests.patch")

        collect_sensor(github_pull_request_polling_sensor, self._context())

        patch_mock.assert_not_called()

    def test_run_key_is_unique_per_repo_and_pr(self, mocker, mock_repos, mock_pr, mock_spec_content):
        mocker.patch("app.definitions.sensors.requests.get", return_value=make_response(mock_repos))
        mocker.patch(
            "app.definitions.sensors.GithubAPI.get_merged_prs_after_number",
            return_value=[mock_pr],
        )
        mocker.patch("app.definitions.sensors.GithubAPI.get_file_contents", return_value=mock_spec_content)
        mocker.patch("app.definitions.sensors.requests.patch", return_value=make_response({}))

        results = collect_sensor(github_pull_request_polling_sensor, self._context())
        run_requests = [r for r in results if isinstance(r, RunRequest)]

        expected_key = f"{mock_repos[0]['id']}-{mock_pr['number']}"
        assert run_requests[0].run_key == expected_key


# ---------------------------------------------------------------------------
# github_run_success_transfer_sensor
# ---------------------------------------------------------------------------

class TestRunSuccessTransferSensor:
    def _context(self, run, event, instance):
        return build_run_status_sensor_context(
            sensor_name="github_run_success_transfer_sensor",
            dagster_instance=instance,
            dagster_run=run,
            dagster_event=event,
        )

    def test_yields_run_request_for_github_triggered_run(
        self, dagster_instance, github_triggered_run, success_event
    ):
        ctx = self._context(github_triggered_run, success_event, dagster_instance)
        results = collect_sensor(github_run_success_transfer_sensor, ctx)

        run_requests = [r for r in results if isinstance(r, RunRequest)]
        assert len(run_requests) == 1
        assert run_requests[0].tags["pr_number"] == "5"
        assert run_requests[0].tags["repo_id"] == "1"
        assert run_requests[0].tags["repo_uri"] == "github.com/org/repo"
        assert run_requests[0].tags["parent_run_id"] == github_triggered_run.run_id

    def test_skips_non_github_run(self, dagster_instance, non_github_run, success_event):
        ctx = self._context(non_github_run, success_event, dagster_instance)
        results = collect_sensor(github_run_success_transfer_sensor, ctx)
        assert any(isinstance(r, SkipReason) for r in results)

    def test_skips_when_pr_number_missing(self, dagster_instance, success_event):
        run = make_dagster_run(tags={"trigger": "github"})  # no pr_number
        ctx = self._context(run, success_event, dagster_instance)
        results = collect_sensor(github_run_success_transfer_sensor, ctx)
        assert any(isinstance(r, SkipReason) for r in results)


# ---------------------------------------------------------------------------
# github_transfer_success_sensor
# ---------------------------------------------------------------------------

class TestTransferSuccessSensor:
    def _context(self, run, event, instance):
        return build_run_status_sensor_context(
            sensor_name="github_transfer_success_sensor",
            dagster_instance=instance,
            dagster_run=run,
            dagster_event=event,
        )

    def test_yields_pr_comment_run_request(
        self, dagster_instance, transfer_completed_run, success_event
    ):
        event = make_success_event(job_name="github_transfer_job")
        ctx = self._context(transfer_completed_run, event, dagster_instance)
        results = collect_sensor(github_transfer_success_sensor, ctx)

        run_requests = [r for r in results if isinstance(r, RunRequest)]
        assert len(run_requests) == 1
        assert run_requests[0].tags["pr_number"] == "5"
        assert run_requests[0].tags["parent_run_id"] == "test-run-id"
