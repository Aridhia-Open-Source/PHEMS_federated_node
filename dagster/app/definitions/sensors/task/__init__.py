from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from app.backend import BackendAPI
from app.config import BackendConfig
from app.definitions.jobs import k8s_pipes_job
from app.definitions.sensors.task.launcher import TaskLauncherSensor
from app.definitions.sensors.task.run_status import TaskRunStatusSensor
from app.utils import BackendAdapter, BackendSession

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"backend_api"},
    job_name="k8s_pipes_job",
)
def task_launcher_sensor(context: OpExecCtx):
    """
    Sensor that launches k8s_pipes_job for the PENDING tasks of enabled projects, whether
    they came from a merged pull request or from the API.
    """
    sensor = TaskLauncherSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
    )
    yield from sensor()


def _record_run_status(context: RunStatusSensorContext):
    """Record the status of a task run on its task."""
    if context.dagster_run.tags.get("trigger") != "task":
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    TaskRunStatusSensor(context=context, backend_api=backend_api)()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.QUEUED,
    default_status=dg.DefaultSensorStatus.STOPPED,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_queued_sensor(context: RunStatusSensorContext):
    """Mark the task QUEUED when its run is queued."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.STARTED,
    default_status=dg.DefaultSensorStatus.STOPPED,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_started_sensor(context: RunStatusSensorContext):
    """Mark the task RUNNING when its run starts."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_success_sensor(context: RunStatusSensorContext):
    """Mark the task SUCCESS when its run succeeds."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=dg.DefaultSensorStatus.STOPPED,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_failure_sensor(context: RunStatusSensorContext):
    """Mark the task FAILED when its run fails."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.CANCELED,
    default_status=dg.DefaultSensorStatus.STOPPED,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_canceled_sensor(context: RunStatusSensorContext):
    """Mark the task CANCELED when its run is canceled."""
    _record_run_status(context)


SENSORS = [
    task_launcher_sensor,
    task_queued_sensor,
    task_started_sensor,
    task_success_sensor,
    task_failure_sensor,
    task_canceled_sensor,
]

JOBS = []
