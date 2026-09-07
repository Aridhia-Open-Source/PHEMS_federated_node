"""Wiring tests: the code location's jobs, sensors and resources, and the
run-status sensors that report task lifecycle back to the backend."""

from unittest.mock import MagicMock, patch

import dagster as dg
import pytest

from app.definitions import defs
from app.definitions.jobs import JOBS, k8s_pipes_job, noop_job
from app.definitions.sensors.github import (
    SENSORS,
    task_cancelled_sensor,
    task_failure_sensor,
    task_queued_sensor,
    task_started_sensor,
    task_success_sensor,
)
from app.tests.conftest import make_dagster_run, make_success_event


BACKEND_ENV = {
    "BACKEND_API_URI": "http://backend.fn.svc:5000",
    "DAGSTER_KC_USER": "dagster",
    "DAGSTER_KC_PASSWORD": "secret",
}


@pytest.fixture
def backend_api(monkeypatch):
    """Stand in for the BackendAPI these sensors build for themselves."""
    for key, value in BACKEND_ENV.items():
        monkeypatch.setenv(key, value)

    api = MagicMock()
    with patch("app.definitions.sensors.github.BackendAdapter"), \
         patch("app.definitions.sensors.github.BackendSession"), \
         patch("app.definitions.sensors.github.BackendAPI", return_value=api):
        yield api


def run_status_context(run, instance):
    return dg.build_run_status_sensor_context(
        sensor_name="test",
        dagster_event=make_success_event(),
        dagster_instance=instance,
        dagster_run=run,
    )


class TestCodeLocation:
    def test_jobs_are_registered(self):
        names = {job.name for job in defs.jobs}

        assert {"noop_job", "k8s_pipes_job", "github_transfer_job"} <= names

    def test_sensors_are_registered(self):
        names = {sensor.name for sensor in defs.sensors}

        assert {
            "pull_request_ingest_sensor",
            "pull_request_trigger_sensor",
            "task_queued_sensor",
            "task_started_sensor",
            "task_success_sensor",
            "task_failure_sensor",
            "task_cancelled_sensor",
        } <= names

    def test_the_pipes_client_is_a_resource(self):
        assert "k8s_pipes_client" in defs.resources

    def test_sensor_resources_are_provided(self):
        """Every resource a sensor declares has to be in the code location."""
        required = set()
        for sensor in SENSORS:
            required |= set(sensor.required_resource_keys or set())

        assert required <= set(defs.resources)

    def test_pipes_job_runs_the_pipes_op(self):
        assert [node.name for node in k8s_pipes_job.graph.nodes] == ["k8s_pipes_op"]

    def test_noop_job_has_no_dependencies(self):
        """It exists to prove a deploy can launch a run pod at all."""
        assert [node.name for node in noop_job.graph.nodes] == ["noop"]

    def test_jobs_are_exported(self):
        assert {job.name for job in JOBS} == {"noop_job", "k8s_pipes_job"}


class TestTaskLifecycleSensors:
    @pytest.mark.parametrize("sensor,status", [
        (task_queued_sensor, "QUEUED"),
        (task_started_sensor, "STARTED"),
        (task_failure_sensor, "FAILURE"),
        (task_cancelled_sensor, "CANCELLED"),
    ])
    def test_status_is_reported_to_the_backend(
        self, backend_api, dagster_instance, github_triggered_run, sensor, status
    ):
        sensor(run_status_context(github_triggered_run, dagster_instance))

        backend_api.patch_pull_request.assert_called_once_with(1, 5, {"status": status})

    @pytest.mark.parametrize("sensor", [
        task_queued_sensor,
        task_started_sensor,
        task_failure_sensor,
        task_cancelled_sensor,
    ])
    def test_runs_from_other_triggers_are_ignored(
        self, backend_api, dagster_instance, non_github_run, sensor
    ):
        sensor(run_status_context(non_github_run, dagster_instance))

        backend_api.patch_pull_request.assert_not_called()

    def test_sensors_run_without_being_switched_on(self):
        """A deploy that needs the sensors enabled by hand reports no PR status."""
        for sensor in (task_queued_sensor, task_started_sensor, task_success_sensor,
                       task_failure_sensor, task_cancelled_sensor):
            assert sensor.default_status == dg.DefaultSensorStatus.RUNNING


class TestTaskSuccessSensor:
    def test_success_reports_and_requests_a_transfer(
        self, backend_api, dagster_instance, github_triggered_run
    ):
        results = list(
            task_success_sensor(run_status_context(github_triggered_run, dagster_instance))
        )

        backend_api.patch_pull_request.assert_called_once_with(1, 5, {"status": "SUCCESS"})
        assert len(results) == 1
        assert results[0].run_key == "5-1-transfer"

    def test_the_transfer_op_is_configured_from_the_run_tags(
        self, backend_api, dagster_instance, github_triggered_run
    ):
        results = list(
            task_success_sensor(run_status_context(github_triggered_run, dagster_instance))
        )

        config = results[0].run_config["ops"]["github_transfer_op"]["config"]
        assert config == {
            "parent_run_id": "test-run-id",
            "pr_number": "5",
            "repo_uri": "github.com/org/repo",
        }

    def test_the_transfer_job_is_tagged_for_its_own_sensors(
        self, backend_api, dagster_instance, github_triggered_run
    ):
        results = list(
            task_success_sensor(run_status_context(github_triggered_run, dagster_instance))
        )

        assert results[0].tags == {
            "trigger": "github_transfer",
            "pr_number": "5",
            "parent_run_id": "test-run-id",
        }

    def test_other_triggers_are_skipped_with_a_reason(
        self, backend_api, dagster_instance, non_github_run
    ):
        results = list(
            task_success_sensor(run_status_context(non_github_run, dagster_instance))
        )

        assert isinstance(results[0], dg.SkipReason)
        assert "manual" in results[0].skip_message
        backend_api.patch_pull_request.assert_not_called()

    def test_an_untagged_run_is_skipped(self, backend_api, dagster_instance):
        run = make_dagster_run(tags={})

        results = list(task_success_sensor(run_status_context(run, dagster_instance)))

        assert isinstance(results[0], dg.SkipReason)
        assert "null" in results[0].skip_message
