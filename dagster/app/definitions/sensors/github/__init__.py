from typing import Generator, cast

import dagster as dg
from dagster import (
    OpExecutionContext as OpExecCtx,
    RunStatusSensorContext,
)

from app.backend import BackendAPI, BackendClient
from app.github import GithubAPI, GithubClient
from app.config import GithubTransferConfig, BackendConfig, GithubConfig
from app.definitions.sensors.github.pr_ingest import PullRequestIngestSensor
from app.definitions.sensors.github.pr_trigger import PullRequestTriggerSensor
from app.definitions.sensors.github.pr_monitor import (
    PullRequestStatusSuccessSensor,
    PullRequestStatusFailureSensor,
)
from app.definitions.jobs import k8s_pipes_job
from app.definitions.sensors.github.transfer_op import GithubTransferOperation

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.op(
    config_schema={
        "parent_run_id": dg.Field(str),
        "pr_number": dg.Field(str),
        "repo_uri": dg.Field(str),
    },
)
def github_transfer_op(context: OpExecCtx):
    """Transfer results to GitHub."""
    github_config = GithubConfig()
    github_api = GithubAPI(GithubClient(github_config.token, base_uri=github_config.base_uri))
    operation = GithubTransferOperation(context, github_api, GithubTransferConfig())
    return operation()


@dg.job
def github_transfer_job():
    """Job to transfer results back to GitHub."""
    github_transfer_op()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    required_resource_keys={"backend_api", "github_api"},
)
def github_pull_request_ingest_sensor(context: OpExecCtx):
    """
    Sensor that polls GitHub for new merged pull requests in configured
    repositories and saves them to the database.

    Flow:
    1. Fetch configured repositories
    2. For each repo, query GitHub for new merged PRs since last cursor
    3. Validate PRs (single watched file, valid spec, correct watch_dir)
    4. Save valid PRs to database
    5. Update repository merge_cursor
    """

    sensor = PullRequestIngestSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        github_api=cast(GithubAPI, context.resources.github_api),
    )
    yield from sensor()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    required_resource_keys={"backend_api", "github_api"},
    job_name="k8s_pipes_job",
)
def github_pull_request_trigger_sensor(context: OpExecCtx):
    """
    Sensor that reads validated, unprocessed PRs from the database and
    triggers task monitoring jobs.

    Flow:
    1. Fetch configured repositories
    2. For each repo, fetch unprocessed valid PRs from database
    3. For each PR, yield a RunRequest to github_task_monitor_job
    4. Job handles task execution and PR status update
    """

    sensor = PullRequestTriggerSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        github_api=cast(GithubAPI, context.resources.github_api),
    )
    yield from sensor()



@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    request_job=github_transfer_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def github_pull_request_status_success_sensor(context: RunStatusSensorContext):
    """
    Monitor k8s_pipes_job completion (triggered by PR trigger sensor).
    On success, mark the PR status as 'success' in the database.
    """
    backend_config = BackendConfig()
    github_config = GithubConfig()
    backend_api = BackendAPI(BackendClient(base_uri=backend_config.uri))
    github_api = GithubAPI(GithubClient(token=github_config.token, base_uri=github_config.base_uri))

    sensor = PullRequestStatusSuccessSensor(
        context=context,
        backend_api=backend_api,
        github_api=github_api,
    )
    yield from sensor()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def github_pr_status_failure_sensor(context: RunStatusSensorContext):
    """
    Monitor k8s_pipes_job completion (triggered by PR trigger sensor).
    On failure, mark the PR status as 'failed' in the database.
    """
    backend_config = BackendConfig()
    github_config = GithubConfig()
    backend_api = BackendAPI(BackendClient(base_uri=backend_config.uri))
    github_api = GithubAPI(GithubClient(token=github_config.token,
                                        base_uri=github_config.base_uri))

    sensor = PullRequestStatusFailureSensor(
        context=context,
        backend_api=backend_api,
        github_api=github_api,
    )
    yield from sensor()


SENSORS = [
    github_pull_request_ingest_sensor,
    github_pull_request_trigger_sensor,
    github_pull_request_status_success_sensor,
    github_pr_status_failure_sensor,
]

JOBS = [github_transfer_job]
