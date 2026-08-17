from unittest.mock import MagicMock

import dagster as dg
import pytest

from app.definitions.sensors.github.pr_status import PullRequestStatusSensor


def make_context(status, tags=None):
    context = MagicMock()
    run = context.dagster_run
    run.status = status
    run.run_id = "run-1"
    run.tags = {"pr_number": "5", "repo_id": "1"} if tags is None else tags
    return context


@pytest.fixture
def backend_api():
    return MagicMock()


def run_sensor(context, backend_api):
    sensor = PullRequestStatusSensor(
        context=context,
        backend_api=backend_api,
        github_api=MagicMock(),
    )
    return list(sensor(context))


class TestStatusMapping:
    @pytest.mark.parametrize("run_status,pr_status", [
        (dg.DagsterRunStatus.QUEUED, "QUEUED"),
        (dg.DagsterRunStatus.STARTED, "STARTED"),
        (dg.DagsterRunStatus.SUCCESS, "SUCCESS"),
        (dg.DagsterRunStatus.FAILURE, "FAILURE"),
        (dg.DagsterRunStatus.CANCELED, "CANCELLED"),
    ])
    def test_run_status_maps_onto_pr_status(self, backend_api, run_status, pr_status):
        run_sensor(make_context(run_status), backend_api)

        backend_api.patch_pull_request.assert_called_once_with(1, 5, {"status": pr_status})

    def test_unmapped_run_status_is_ignored(self, backend_api):
        context = make_context(dg.DagsterRunStatus.NOT_STARTED)

        assert run_sensor(context, backend_api) == []
        backend_api.patch_pull_request.assert_not_called()
        context.log.warning.assert_called_once()


class TestTags:
    @pytest.mark.parametrize("tags", [
        {},
        {"pr_number": "5"},
        {"repo_id": "1"},
    ])
    def test_runs_without_pr_tags_are_skipped(self, backend_api, tags):
        context = make_context(dg.DagsterRunStatus.SUCCESS, tags=tags)

        assert run_sensor(context, backend_api) == []
        backend_api.patch_pull_request.assert_not_called()
        context.log.error.assert_called_once()

    def test_tags_are_converted_to_ints(self, backend_api):
        context = make_context(dg.DagsterRunStatus.SUCCESS, tags={
            "pr_number": "12", "repo_id": "34",
        })

        run_sensor(context, backend_api)

        assert backend_api.patch_pull_request.call_args.args[:2] == (34, 12)


class TestTransferTrigger:
    def test_success_triggers_the_transfer_job(self, backend_api):
        results = run_sensor(make_context(dg.DagsterRunStatus.SUCCESS), backend_api)

        assert len(results) == 1
        assert isinstance(results[0], dg.RunRequest)
        assert results[0].run_key == "5-transfer"
        assert results[0].tags == {
            "trigger": "github_transfer",
            "pr_number": "5",
            "parent_run_id": "run-1",
        }

    def test_failure_does_not_trigger_a_transfer(self, backend_api):
        assert run_sensor(make_context(dg.DagsterRunStatus.FAILURE), backend_api) == []

    def test_a_failed_patch_does_not_raise(self, backend_api):
        backend_api.patch_pull_request.side_effect = RuntimeError("backend down")
        context = make_context(dg.DagsterRunStatus.SUCCESS)

        assert run_sensor(context, backend_api) == []
        context.log.error.assert_called_once()
