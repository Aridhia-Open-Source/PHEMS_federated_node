from datetime import datetime, timezone

import dagster as dg
from dagster import RunStatusSensorContext

from app.backend import BackendAPI
from app.definitions.sensors.base import BaseSensor
from app.models import TaskStatus


class TaskRunStatusSensor(BaseSensor):
    """Mirrors the status of a task's Dagster run onto the task. Nothing else writes Task.status."""

    STATUS_MAP = {
        dg.DagsterRunStatus.QUEUED: TaskStatus.QUEUED,
        dg.DagsterRunStatus.STARTED: TaskStatus.RUNNING,
        dg.DagsterRunStatus.SUCCESS: TaskStatus.SUCCESS,
        dg.DagsterRunStatus.FAILURE: TaskStatus.FAILED,
        dg.DagsterRunStatus.CANCELED: TaskStatus.CANCELED,
    }

    def __init__(self, context: RunStatusSensorContext, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Patches the task to the status the run moved to.

        When the run starts the task records the run id and start time. When it ends the
        task records the end time. The exit code is not recorded: the run does not expose it.
        """
        run = self.context.dagster_run
        task_status = self.STATUS_MAP[run.status]
        task_id = int(run.tags["task_id"])

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields = {"status": task_status.value}
        if run.status == dg.DagsterRunStatus.STARTED:
            fields["dagster_run_id"] = run.run_id
            fields["started_at"] = now
        elif run.status != dg.DagsterRunStatus.QUEUED:
            fields["completed_at"] = now

        self.backend_api.patch_task(task_id, fields)
        self.log.info(f"Updated task {task_id} to status: {task_status.value}")
