from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.backend import BackendAPI
from app.definitions.sensors.git.base import GitAPIFactory
from app.definitions.sensors.git.pr_ingest import PullRequestIngestSensor
from app.definitions.sensors.git.pr_process import PullRequestProcessSensor

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"backend_api", "git_apis"},
)
def git_pull_request_ingest_sensor(context: OpExecCtx):
    """
    Sensor that polls the git provider for new merged pull requests in configured
    repositories and saves them to the database.

    Flow:
    1. Fetch configured repositories
    2. For each repo, build its api client and query the provider for merged PRs since
       the repo's cursor
    3. Fetch each PR and save the batch as UNKNOWN
    """
    sensor = PullRequestIngestSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
    )
    yield from sensor()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"backend_api", "git_apis"},
)
def git_pull_request_process_sensor(context: OpExecCtx):
    """
    Sensor that reads the spec of each UNKNOWN pull request in the trigger repositories
    of enabled projects and raises its task request.

    Flow:
    1. Fetch the repositories of enabled projects
    2. For each UNKNOWN PR, find the new spec file in the repository's watch_dir
    3. No such file is IGNORED, several or an invalid spec is INVALID, else the task
       request is created and the PR is READY with its spec as payload
    """
    sensor = PullRequestProcessSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
    )
    yield from sensor()


SENSORS = [
    git_pull_request_ingest_sensor,
    git_pull_request_process_sensor,
]

JOBS = []
