from types import SimpleNamespace
from unittest.mock import MagicMock

import dagster as dg
import pytest
import requests

from app.definitions.sensors.task import SENSORS, task_reconcile_sensor
from app.definitions.sensors.task.reconcile import TaskReconcileSensor

START_TIME = 1699999990.0
END_TIME = 1700000000.0
S = dg.DagsterRunStatus


class World:
    """A backend with stateful tasks and a Dagster instance with runs, as the sensor sees them."""

    def __init__(self):
        self.projects = {1: True, 2: False}  # id -> enabled
        self.tasks = {}  # id -> SimpleNamespace(id, project_id, attempt, status)
        self.runs = {}  # (task id, attempt) -> run
        self.patches = []
        self.refuse = {}  # task id -> exception raised by patch_task
        self.backend_api = MagicMock()
        self.backend_api.get_projects.side_effect = lambda enabled=None: [
            SimpleNamespace(id=pid) for pid, on in self.projects.items() if enabled is None or on == enabled
        ]
        self.backend_api.get_tasks.side_effect = lambda status, project_id: [
            t for t in self.tasks.values() if t.status == status and t.project_id == project_id
        ]
        self.backend_api.patch_task.side_effect = self.patch_task
        self.instance = MagicMock()
        self.instance.get_runs.side_effect = self.get_runs
        self.instance.get_run_record_by_id.return_value = SimpleNamespace(start_time=START_TIME, end_time=END_TIME)

    def add_task(self, task_id, status, project_id=1, attempt=1, run_status=None):
        self.tasks[task_id] = SimpleNamespace(id=task_id, project_id=project_id, attempt=attempt, status=status)
        if run_status is not None:
            self.runs[(task_id, attempt)] = SimpleNamespace(status=run_status, run_id=f"run-{task_id}-{attempt}")

    def get_runs(self, filters, limit):
        assert filters.tags["trigger"] == "task"
        run = self.runs.get((int(filters.tags["task_id"]), int(filters.tags["attempt"])))
        return [run] if run else []

    def patch_task(self, project_id, task_id, fields):
        self.patches.append((project_id, task_id, fields))
        if task_id in self.refuse:
            raise self.refuse[task_id]
        self.tasks[task_id].status = fields["status"]

    def tick(self):
        sensor = TaskReconcileSensor(SimpleNamespace(instance=self.instance, log=MagicMock()), self.backend_api)
        return list(sensor())


@pytest.fixture
def world():
    return World()


@pytest.mark.parametrize("task_status", ["PENDING", "QUEUED", "RUNNING"])
@pytest.mark.parametrize("run_status,final", [(S.SUCCESS, "SUCCESS"), (S.FAILURE, "FAILED"), (S.CANCELED, "CANCELED")])
def test_a_run_that_finished_unseen_patches_the_final_status(world, task_status, run_status, final):
    world.add_task(9, task_status, run_status=run_status)

    world.tick()

    assert world.patches == [(1, 9, {
        "status": final,
        "executor_run_id": "run-9-1",
        "completed_at": "2023-11-14T22:13:20Z",
        "started_at": "2023-11-14T22:13:10Z",
    })]


def test_a_started_run_sets_a_pending_task_running_with_the_start_time(world):
    world.add_task(9, "PENDING", run_status=S.STARTED)

    world.tick()

    (_, _, fields), = world.patches
    assert fields["status"] == "RUNNING" and fields["executor_run_id"] == "run-9-1" and "started_at" in fields


def test_a_queued_run_sets_a_pending_task_queued(world):
    world.add_task(9, "PENDING", run_status=S.QUEUED)

    world.tick()

    assert world.patches[0][2]["status"] == "QUEUED"


@pytest.mark.parametrize("task_status,run_status", [("RUNNING", S.STARTED), ("QUEUED", S.QUEUED)])
def test_a_run_in_flight_with_the_matching_status_is_not_patched(world, task_status, run_status):
    world.add_task(9, task_status, run_status=run_status)

    world.tick()

    assert not world.patches


@pytest.mark.parametrize("run_status", [S.STARTING, S.NOT_STARTED, S.CANCELING])
def test_a_run_status_without_a_task_counterpart_is_left_alone(world, run_status):
    world.add_task(9, "QUEUED", run_status=run_status)

    world.tick()

    assert not world.patches


def test_a_pending_task_without_a_run_is_left_alone(world):
    world.add_task(9, "PENDING")

    world.tick()

    assert not world.patches


def test_the_run_of_the_task_attempt_is_the_one_used(world):
    world.add_task(9, "PENDING", attempt=2)
    world.runs[(9, 1)] = SimpleNamespace(status=S.FAILURE, run_id="run-9-1")  # the previous attempt

    world.tick()

    assert not world.patches


def test_a_409_is_skipped_and_the_others_go_on(world):
    world.add_task(1, "RUNNING", run_status=S.SUCCESS)
    world.add_task(2, "RUNNING", run_status=S.SUCCESS)
    world.refuse[1] = requests.HTTPError(response=MagicMock(status_code=409, text="finished"))

    world.tick()

    assert [p[1] for p in world.patches] == [1, 2] and world.tasks[2].status == "SUCCESS"


def test_an_error_on_one_task_does_not_stop_the_others(world):
    world.add_task(1, "RUNNING", run_status=S.SUCCESS)
    world.add_task(2, "RUNNING", run_status=S.FAILURE)
    world.refuse[1] = requests.HTTPError(response=MagicMock(status_code=500))

    world.tick()

    assert world.tasks[1].status == "RUNNING" and world.tasks[2].status == "FAILED"


def test_an_error_reading_the_runs_does_not_stop_the_others(world):
    world.add_task(1, "RUNNING", run_status=S.SUCCESS)
    world.add_task(2, "RUNNING", run_status=S.SUCCESS)
    real = world.instance.get_runs.side_effect
    world.instance.get_runs.side_effect = lambda filters, limit: (
        (_ for _ in ()).throw(RuntimeError("db down")) if filters.tags["task_id"] == "1" else real(filters, limit)
    )

    world.tick()

    assert [p[1] for p in world.patches] == [2]


def test_a_task_of_a_disabled_project_is_not_touched(world):
    world.add_task(9, "RUNNING", project_id=2, run_status=S.SUCCESS)

    world.tick()

    assert not world.patches
    world.backend_api.get_projects.assert_called_with(enabled=True)


def test_a_second_tick_makes_no_further_patches(world):
    world.add_task(1, "RUNNING", run_status=S.SUCCESS)
    world.add_task(2, "PENDING", run_status=S.STARTED)
    world.add_task(3, "PENDING")

    world.tick()
    first = len(world.patches)
    world.tick()

    assert first == 2 and len(world.patches) == first


def test_the_tick_yields_a_skip_reason(world):
    assert all(isinstance(r, dg.SkipReason) for r in world.tick())


def test_the_registered_sensor_runs_with_a_context(dagster_instance, monkeypatch):
    world = World()
    monkeypatch.setattr(dagster_instance, "get_runs", world.get_runs)
    monkeypatch.setattr(dagster_instance, "get_run_record_by_id", world.instance.get_run_record_by_id)
    world.add_task(9, "RUNNING", run_status=S.SUCCESS)
    context = dg.build_sensor_context(resources={"backend_api": world.backend_api}, instance=dagster_instance)

    result = task_reconcile_sensor.evaluate_tick(context)
    assert result.skip_message == "Reconciled 1 tasks."

    assert world.tasks[9].status == "SUCCESS"


def test_the_sensor_is_registered_stopped_with_no_job():
    assert task_reconcile_sensor in SENSORS
    assert task_reconcile_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert not task_reconcile_sensor.targets
