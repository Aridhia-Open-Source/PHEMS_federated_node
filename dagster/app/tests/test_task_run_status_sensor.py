from unittest.mock import MagicMock, patch

import dagster as dg
import pytest

from app.definitions.sensors.task_request import (
    SENSORS,
    task_request_canceled_sensor,
    task_request_failure_sensor,
    task_request_started_sensor,
    task_request_success_sensor,
)
from app.definitions.sensors.task_request.run_status import TaskRunStatusSensor
from app.models import TaskStatus
from app.tests.conftest import make_dagster_run, make_success_event

TAGS = {"trigger": "task_request", "task_request_id": "3", "task_id": "9"}


def sensor_for(status, tags=TAGS, backend_api=None):
    run = make_dagster_run(tags=tags).with_status(status)
    context = MagicMock(dagster_run=run)
    return TaskRunStatusSensor(context=context, backend_api=backend_api or MagicMock()), context


def test_started_unqueues_the_request_and_marks_the_task_running():
    backend_api = MagicMock()
    sensor, _ = sensor_for(dg.DagsterRunStatus.STARTED, backend_api=backend_api)

    sensor()

    backend_api.patch_task_request.assert_called_once_with(3, {"queued": False})
    (task_id, fields), _ = backend_api.patch_task.call_args
    assert task_id == 9
    assert fields["status"] == TaskStatus.RUNNING.value
    assert fields["dagster_run_id"] == "test-run-id"
    assert "started_at" in fields and "completed_at" not in fields


@pytest.mark.parametrize("status,task_status", [
    (dg.DagsterRunStatus.SUCCESS, TaskStatus.SUCCESS),
    (dg.DagsterRunStatus.FAILURE, TaskStatus.FAILURE),
    (dg.DagsterRunStatus.CANCELED, TaskStatus.CANCELLED),
])
def test_end_of_run_marks_the_task_with_its_end_time(status, task_status):
    backend_api = MagicMock()
    sensor, _ = sensor_for(status, backend_api=backend_api)

    sensor()

    backend_api.patch_task_request.assert_not_called()
    (task_id, fields), _ = backend_api.patch_task.call_args
    assert task_id == 9
    assert fields["status"] == task_status.value
    assert "completed_at" in fields and "started_at" not in fields
    assert "exit_code" not in fields


def test_a_failing_task_request_patch_is_logged_and_the_task_is_still_patched():
    backend_api = MagicMock()
    backend_api.patch_task_request.side_effect = RuntimeError("500")
    sensor, context = sensor_for(dg.DagsterRunStatus.STARTED, backend_api=backend_api)

    sensor()

    context.log.error.assert_called_once()
    backend_api.patch_task.assert_called_once()


def test_a_failing_task_patch_is_logged_and_does_not_raise():
    backend_api = MagicMock()
    backend_api.patch_task.side_effect = RuntimeError("500")
    sensor, context = sensor_for(dg.DagsterRunStatus.SUCCESS, backend_api=backend_api)

    sensor()

    context.log.error.assert_called_once()


def test_missing_task_tags_patch_nothing():
    backend_api = MagicMock()
    sensor, context = sensor_for(
        dg.DagsterRunStatus.STARTED, tags={"trigger": "task_request"}, backend_api=backend_api
    )

    sensor()

    context.log.error.assert_called_once()
    backend_api.patch_task.assert_not_called()
    backend_api.patch_task_request.assert_not_called()


@pytest.fixture
def backend_api(monkeypatch):
    for key, value in {
        "BACKEND_API_URI": "http://backend.fn.svc:5000",
        "DAGSTER_KC_USER": "dagster",
        "DAGSTER_KC_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(key, value)

    api = MagicMock()
    with patch("app.definitions.sensors.task_request.BackendAdapter"), \
         patch("app.definitions.sensors.task_request.BackendSession"), \
         patch("app.definitions.sensors.task_request.BackendAPI", return_value=api):
        yield api


def context_for(run, instance):
    return dg.build_run_status_sensor_context(
        sensor_name="test",
        dagster_event=make_success_event(),
        dagster_instance=instance,
        dagster_run=run,
    )


def test_registered_sensor_patches_for_task_request_runs(backend_api, dagster_instance):
    run = make_dagster_run(tags=TAGS).with_status(dg.DagsterRunStatus.SUCCESS)

    task_request_success_sensor(context_for(run, dagster_instance))

    backend_api.patch_task.assert_called_once()
    assert backend_api.patch_task.call_args[0][1]["status"] == "SUCCESS"


def test_registered_sensor_ignores_runs_of_other_triggers(backend_api, dagster_instance):
    run = make_dagster_run(tags={"trigger": "gitea"}).with_status(dg.DagsterRunStatus.SUCCESS)

    task_request_success_sensor(context_for(run, dagster_instance))

    backend_api.patch_task.assert_not_called()


def test_run_status_sensors_are_registered_and_stopped_by_default():
    sensors = [task_request_started_sensor, task_request_success_sensor,
               task_request_failure_sensor, task_request_canceled_sensor]

    assert all(s in SENSORS for s in sensors)
    assert all(s.default_status == dg.DefaultSensorStatus.STOPPED for s in sensors)
