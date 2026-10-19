"""
Safety net for the run-status sensors. They react to a run changing status, so a task whose run
started or finished while they were stopped keeps a stale status. This sensor reads the run's
current status every tick instead.
"""
from http import HTTPStatus
from typing import cast

import requests
import dagster as dg
from dagster import SensorEvaluationContext

from app.backend import BackendAPI
from app.config import DEFAULT_SENSOR_STATUS, MIN_SENSOR_INTERVAL_SECONDS
from app.definitions.jobs import k8s_pipes_job
from app.definitions.sensors.base import BaseSensor
from app.definitions.sensors.task.run_status import TaskRunStatusSensor
from app.models import Task, TaskStatus

UNFINISHED = [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]


class TaskReconcileSensor(BaseSensor):
    """Sets each unfinished task of an enabled project to the current status of its Dagster run."""

    def __init__(self, context: SensorEvaluationContext, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Patches a task whose status differs from its run's, and yields a SkipReason.

        The run is found by the tags the launcher gives it: trigger=task, task_id and attempt (the run key
        is task/<id>/<attempt>). The status maps and the fields are the run-status sensors' (see
        TaskRunStatusSensor.task_fields). Left alone: a PENDING task without a run (the launcher owns it),
        a run in a status the task has no counterpart for (e.g. STARTING), and a task that already has the
        status. A 409 (the task moved on) is skipped; an error on one task is logged and the others go on.
        """
        patched = 0
        for project in self.backend_api.get_projects(enabled=True):
            for status in UNFINISHED:
                for task in self.backend_api.get_tasks(status=status.value, project_id=project.id):
                    try:
                        patched += self._reconcile(project.id, task)
                    except Exception as e:  # pylint: disable=broad-exception-caught  # one task must not stop the others
                        self.log.exception(f"Task {task.id} not reconciled: {e!r}")
        yield dg.SkipReason(f"Reconciled {patched} tasks.")

    def _reconcile(self, project_id: int, task: Task) -> int:
        """Patches the task to its run's status. Returns 1 if it was patched, else 0."""
        runs = self.context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=k8s_pipes_job.name,
                tags={"trigger": "task", "task_id": str(task.id), "attempt": str(task.attempt)},
            ),
            limit=1,
        )
        if not runs or runs[0].status not in TaskRunStatusSensor.STATUS_MAP:
            return 0
        task_status, fields = TaskRunStatusSensor.task_fields(runs[0], self.context.instance)
        if task_status.value == task.status:
            return 0
        try:
            self.backend_api.patch_task(project_id, task.id, fields)
        except requests.HTTPError as e:
            if e.response.status_code != HTTPStatus.CONFLICT:
                raise
            self.log.warning(f"Task {task.id} not moved to {task_status.value}: {e.response.text}")
            return 0
        self.log.info(f"Reconciled task {task.id} from {task.status} to {task_status.value}")
        return 1


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api"},
)
def task_reconcile_sensor(context: SensorEvaluationContext):
    """Every tick, set each unfinished task to the current status of its run, as the run-status sensors would have."""
    sensor = TaskReconcileSensor(context=context, backend_api=cast(BackendAPI, context.resources.backend_api))
    yield from sensor()
