from datetime import datetime, timezone
from http import HTTPStatus

import requests
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

        Every status records the run id, so a run that skips one still leaves it on the task.
        When the run starts the task records the start time. When it reaches a terminal status
        the task records the time the run ended, and the time it started from the run itself.
        The exit code is not recorded: the run does not expose it.
        A finished task refuses a status change with a 409, which is skipped.
        """
        run = self.context.dagster_run
        task_status = self.STATUS_MAP[run.status]
        task_id = int(run.tags["task_id"])
        project_id = int(run.tags["project_id"])

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields = {"status": task_status.value, "executor_run_id": run.run_id}
        if run.status == dg.DagsterRunStatus.STARTED:
            fields["started_at"] = now
        elif task_status in self.TERMINAL_STATUSES:
            record = self.context.instance.get_run_record_by_id(run.run_id)
            fields["completed_at"] = datetime.fromtimestamp(record.end_time, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            # A short run can go from STARTED to its end between two ticks, so the STARTED event was never seen:
            # take the start from the run itself.
            if record.start_time is not None:
                fields["started_at"] = datetime.fromtimestamp(record.start_time, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

        try:
            self.backend_api.patch_task(project_id, task_id, fields)
        except requests.HTTPError as e:
            if e.response.status_code != HTTPStatus.CONFLICT:
                raise
            # The task finished already and keeps its status
            self.log.warning(f"Task {task_id} not moved to {task_status.value}: {e.response.text}")
            return
        self.log.info(f"Updated task {task_id} to status: {task_status.value}")
