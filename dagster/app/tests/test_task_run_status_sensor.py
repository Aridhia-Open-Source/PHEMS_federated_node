from unittest.mock import MagicMock, patch

import dagster as dg
import pytest

from app.definitions.sensors.task import (
    SENSORS,
    task_canceled_sensor,
    task_failure_sensor,
    task_queued_sensor,
    task_started_sensor,
    task_success_sensor,
)
from app.definitions.sensors.task.run_status import TaskRunStatusSensor
from app.tests.conftest import make_dagster_run, make_success_event

TAGS = {"trigger": "task", "task_id": "9", "attempt": "1"}
END_TIME = 1700000000.0


def sensor_for(status, tags=TAGS, backend_api=None):
    # A queued run cannot be built without a code origin, so the run is a stand-in
    run = MagicMock(status=status, run_id="test-run-id", tags=tags)
    context = MagicMock(dagster_run=run)
    context.instance.get_run_record_by_id.return_value.end_time = END_TIME
    return TaskRunStatusSensor(context=context, backend_api=backend_api or MagicMock())


@pytest.mark.parametrize("status,task_status,time_field", [
    (dg.DagsterRunStatus.QUEUED, "QUEUED", None),
    (dg.DagsterRunStatus.STARTED, "RUNNING", "started_at"),
    (dg.DagsterRunStatus.SUCCESS, "SUCCESS", "completed_at"),
    (dg.DagsterRunStatus.FAILURE, "FAILED", "completed_at"),
    (dg.DagsterRunStatus.CANCELED, "CANCELED", "completed_at"),
])
def test_the_run_status_maps_to_the_task_status(status, task_status, time_field):
    backend_api = MagicMock()

    sensor_for(status, backend_api=backend_api)()

    (task_id, fields), _ = backend_api.patch_task.call_args
    assert task_id == 9
    assert fields["status"] == task_status
    assert set(fields) - {"status", "dagster_run_id"} == ({time_field} if time_field else set())
    assert fields["dagster_run_id"] == "test-run-id"
    if time_field == "completed_at":
        assert fields["completed_at"] == "2023-11-14T22:13:20Z"


def test_the_map_covers_exactly_the_statuses_the_sensors_monitor():
    assert set(TaskRunStatusSensor.STATUS_MAP) == {
        dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.STARTED, dg.DagsterRunStatus.SUCCESS,
        dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED,
    }


@pytest.fixture
def backend_api(monkeypatch):
    for key, value in {
        "BACKEND_API_URI": "http://backend.fn.svc:5000",
        "DAGSTER_KC_USER": "dagster",
        "DAGSTER_KC_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(key, value)

    api = MagicMock()
    with patch("app.definitions.sensors.task.BackendAdapter"), \
         patch("app.definitions.sensors.task.BackendSession"), \
         patch("app.definitions.sensors.task.BackendAPI", return_value=api):
        yield api


def context_for(run, instance):
    return dg.build_run_status_sensor_context(
        sensor_name="test",
        dagster_event=make_success_event(),
        dagster_instance=instance,
        dagster_run=run,
    )


def test_registered_sensor_patches_for_task_runs(backend_api, dagster_instance, monkeypatch):
    monkeypatch.setattr(
        dagster_instance, "get_run_record_by_id", lambda run_id: MagicMock(end_time=END_TIME)
    )
    run = make_dagster_run(tags=TAGS).with_status(dg.DagsterRunStatus.SUCCESS)

    task_success_sensor(context_for(run, dagster_instance))

    backend_api.patch_task.assert_called_once()
    assert backend_api.patch_task.call_args[0][1]["status"] == "SUCCESS"


def test_registered_sensor_ignores_runs_of_other_triggers(backend_api, dagster_instance):
    run = make_dagster_run(tags={"trigger": "manual"}).with_status(dg.DagsterRunStatus.SUCCESS)

    task_success_sensor(context_for(run, dagster_instance))

    backend_api.patch_task.assert_not_called()


def test_run_status_sensors_are_registered_and_stopped_by_default():
    sensors = [task_queued_sensor, task_started_sensor, task_success_sensor,
               task_failure_sensor, task_canceled_sensor]

    assert all(s in SENSORS for s in sensors)
    assert all(s.default_status == dg.DefaultSensorStatus.STOPPED for s in sensors)
