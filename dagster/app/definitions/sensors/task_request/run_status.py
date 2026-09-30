from datetime import datetime, timezone

import dagster as dg
from dagster import RunStatusSensorContext

from app.backend import BackendAPI
from app.definitions.sensors.base import BaseSensor
from app.models import TaskStatus


class TaskRunStatusSensor(BaseSensor):
    """Records the lifecycle of a task request's run on its task and request."""

    STATUS_MAP = {
        dg.DagsterRunStatus.STARTED: TaskStatus.RUNNING,
        dg.DagsterRunStatus.SUCCESS: TaskStatus.SUCCESS,
        dg.DagsterRunStatus.FAILURE: TaskStatus.FAILURE,
        dg.DagsterRunStatus.CANCELED: TaskStatus.CANCELLED,
    }

    def __init__(self, context: RunStatusSensorContext, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Patches the task to the status the run moved to.

        When the run starts the request is no longer queued and the task records the run
        id and start time. When it ends the task records the end time. The exit code is
        not recorded: the run does not expose it. PullRequest status is not touched.
        """
        run = self.context.dagster_run

        task_status = self.STATUS_MAP.get(run.status)
        if not task_status:
            self.log.warning(f"Unknown run status: {run.status.value}")
            return

        task_request_id = run.tags.get("task_request_id")
        task_id = run.tags.get("task_id")
        if not task_request_id or not task_id:
            self.log.error(
                f"Missing task tags on run {run.run_id}: "
                f"task_request_id={task_request_id}, task_id={task_id}"
            )
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        task_fields = {"status": task_status.value}
        if run.status == dg.DagsterRunStatus.STARTED:
            task_fields["dagster_run_id"] = run.run_id
            task_fields["started_at"] = now
            try:
                self.backend_api.patch_task_request(int(task_request_id), {"queued": False})
                self.log.info(f"Task request {task_request_id} is no longer queued")
            except Exception as e:
                self.log.error(f"Failed to update task request {task_request_id}: {e}")
        else:
            task_fields["completed_at"] = now

        try:
            self.backend_api.patch_task(int(task_id), task_fields)
            self.log.info(f"Updated task {task_id} to status: {task_status.value}")
        except Exception as e:
            self.log.error(f"Failed to update task {task_id}: {e}")
