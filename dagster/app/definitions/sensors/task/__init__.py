from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from fednode.clients.nexus.client import BackendAPI
from app.settings import settings
from app.definitions.jobs import k8s_pipes_job
from app.definitions.sensors.task import delivery, pull_request_sync
from app.definitions.sensors.task.launcher import TaskLauncherSensor
from app.definitions.sensors.task.reconcile import task_reconcile_sensor
from app.definitions.sensors.task.run_status import TaskRunStatusSensor
from fednode.http import BackendSession, PasswordFileAdapter


@dg.sensor(
    minimum_interval_seconds=settings.sensors.min_interval_seconds,
    default_status=settings.sensors.initial_status,
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
    if context.dagster_run.tags.get("fn/trigger") != "task":
        return

    backend_config = settings.services.nexus
    timeout = (settings.http.connect_timeout, settings.http.read_timeout)
    backend_adapter = PasswordFileAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password_file=backend_config.password_file,
        timeout=timeout,
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_session.timeout = timeout
    backend_api = BackendAPI(session=backend_session)

    TaskRunStatusSensor(context=context, backend_api=backend_api)()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.QUEUED,
    default_status=settings.sensors.initial_status,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=settings.sensors.min_interval_seconds,
)
def task_queued_sensor(context: RunStatusSensorContext):
    """Mark the task QUEUED when its run is queued."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.STARTED,
    default_status=settings.sensors.initial_status,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=settings.sensors.min_interval_seconds,
)
def task_started_sensor(context: RunStatusSensorContext):
    """Mark the task RUNNING when its run starts."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=settings.sensors.initial_status,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=settings.sensors.min_interval_seconds,
)
def task_success_sensor(context: RunStatusSensorContext):
    """Mark the task SUCCESS when its run succeeds."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=settings.sensors.initial_status,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=settings.sensors.min_interval_seconds,
)
def task_failure_sensor(context: RunStatusSensorContext):
    """Mark the task FAILED when its run fails."""
    _record_run_status(context)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.CANCELED,
    default_status=settings.sensors.initial_status,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=settings.sensors.min_interval_seconds,
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
    task_reconcile_sensor,
    delivery.task_results_delivery_sensor,
    delivery.results_delivery_retry_sensor,
    pull_request_sync.results_pull_request_sync_sensor,
]

JOBS = [delivery.deliver_results_job, pull_request_sync.sync_results_pull_requests_job,
        pull_request_sync.open_results_pull_request_job]
