from typing import cast

import dagster as dg
from dagster import (
    OpExecutionContext as OpExecCtx,
    RunStatusSensorContext,
)

from app.backend import BackendAPI
from app.utils import BackendAdapter, BackendSession
from app.gitea import GiteaAPI, GiteaClient
from app.config import GiteaConfig, BackendConfig
from app.definitions.sensors.gitea.pr_ingest import PullRequestIngestSensor
from app.definitions.sensors.gitea.pr_trigger import PullRequestTriggerSensor
from app.definitions.sensors.gitea.pr_status import PullRequestStatusSensor
from app.definitions.jobs import k8s_pipes_job

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    required_resource_keys={"backend_api", "gitea_api"},
)
def gitea_pull_request_ingest_sensor(context: OpExecCtx):
    """Polls Gitea for new merged pull requests in configured repositories."""
    sensor = PullRequestIngestSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        gitea_api=cast(GiteaAPI, context.resources.gitea_api),
    )
    yield from sensor()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    required_resource_keys={"backend_api", "gitea_api"},
    job_name="k8s_pipes_job",
)
def gitea_pull_request_trigger_sensor(context: OpExecCtx):
    """Reads validated, unprocessed PRs from database and triggers task monitoring jobs."""
    sensor = PullRequestTriggerSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        gitea_api=cast(GiteaAPI, context.resources.gitea_api),
    )
    yield from sensor()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.QUEUED,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def gitea_task_queued_sensor(context: RunStatusSensorContext):
    """Update PR status when task is queued."""
    run = context.dagster_run
    if run.tags.get("trigger") != "gitea":
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    backend_api.patch_pull_request(
        int(run.tags["repo_id"]),
        int(run.tags["pr_number"]),
        {"status": "QUEUED"},
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.STARTED,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def gitea_task_started_sensor(context: RunStatusSensorContext):
    """Update PR status when task starts."""
    run = context.dagster_run
    if run.tags.get("trigger") != "gitea":
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    backend_api.patch_pull_request(
        int(run.tags["repo_id"]),
        int(run.tags["pr_number"]),
        {"status": "STARTED"},
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def gitea_task_success_sensor(context: RunStatusSensorContext):
    """Update PR status when task succeeds."""
    run = context.dagster_run
    if run.tags.get("trigger") != "gitea":
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    backend_api.patch_pull_request(
        int(run.tags["repo_id"]),
        int(run.tags["pr_number"]),
        {"status": "SUCCESS"},
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def gitea_task_failure_sensor(context: RunStatusSensorContext):
    """Update PR status when task fails."""
    run = context.dagster_run
    if run.tags.get("trigger") != "gitea":
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    backend_api.patch_pull_request(
        int(run.tags["repo_id"]),
        int(run.tags["pr_number"]),
        {"status": "FAILURE"},
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.CANCELED,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def gitea_task_canceled_sensor(context: RunStatusSensorContext):
    """Update PR status when task is canceled."""
    run = context.dagster_run
    if run.tags.get("trigger") != "gitea":
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    backend_api.patch_pull_request(
        int(run.tags["repo_id"]),
        int(run.tags["pr_number"]),
        {"status": "CANCELLED"},
    )


SENSORS = [
    gitea_pull_request_ingest_sensor,
    gitea_pull_request_trigger_sensor,
    gitea_task_queued_sensor,
    gitea_task_started_sensor,
    gitea_task_success_sensor,
    gitea_task_failure_sensor,
    gitea_task_canceled_sensor,
]

JOBS = []
