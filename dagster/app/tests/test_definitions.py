"""Wiring tests: the code location's jobs, sensors and resources."""

import dagster as dg

from app.definitions import defs
from app.definitions.jobs import JOBS, k8s_pipes_job, noop_job
from app.definitions.sensors import SENSORS


class TestCodeLocation:
    def test_jobs_are_registered(self):
        names = {job.name for job in defs.jobs}

        assert {"noop_job", "k8s_pipes_job", "github_transfer_job",
                "evaluate_repository_pull_requests_job", "deliver_results_job"} <= names

    def test_sensors_are_registered(self):
        names = {sensor.name for sensor in defs.sensors}

        assert {
            "git_pull_request_ingest_sensor",
            "git_pull_request_evaluate_sensor",
            "task_launcher_sensor",
            "task_queued_sensor",
            "task_started_sensor",
            "task_success_sensor",
            "task_failure_sensor",
            "task_canceled_sensor",
            "task_results_delivery_sensor",
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

    def test_every_sensor_is_stopped_by_default(self):
        assert all(s.default_status == dg.DefaultSensorStatus.STOPPED for s in SENSORS)
