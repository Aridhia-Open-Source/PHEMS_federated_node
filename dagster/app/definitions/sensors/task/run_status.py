from datetime import datetime, timezone

import dagster as dg
from dagster import RunStatusSensorContext

from app.backend import BackendAPI
from app.definitions.sensors.base import BaseSensor
from app.models import TaskStatus


class TaskRunStatusSensor(BaseSensor):
    """Mirrors the status of a task's Dagster run onto the task. Nothing else writes Task.status."""

    # Dagster statuses that share a name with a task status map onto it. The rest are renamed.
    STATUS_MAP = {
        run_status: TaskStatus[run_status.name]
        for run_status in dg.DagsterRunStatus
        if run_status.name in TaskStatus.__members__
    } | {
        dg.DagsterRunStatus.STARTED: TaskStatus.RUNNING,
        dg.DagsterRunStatus.FAILURE: TaskStatus.FAILED,
    }
    TERMINAL_STATUSES = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELED}

    def __init__(self, context: RunStatusSensorContext, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Patches the task to the status the run moved to.

        When the run starts the task records the run id and start time. When it reaches a
        terminal status the task records the time the run ended.
        The exit code is not recorded: the run does not expose it.
        """
        run = self.context.dagster_run
        task_status = self.STATUS_MAP[run.status]
        task_id = int(run.tags["task_id"])

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields = {"status": task_status.value}
        if run.status == dg.DagsterRunStatus.STARTED:
            fields["dagster_run_id"] = run.run_id
            fields["started_at"] = now
        elif task_status in self.TERMINAL_STATUSES:
            end_time = self.context.instance.get_run_record_by_id(run.run_id).end_time
            fields["completed_at"] = datetime.fromtimestamp(end_time, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        self.backend_api.patch_task(task_id, fields)
        self.log.info(f"Updated task {task_id} to status: {task_status.value}")
