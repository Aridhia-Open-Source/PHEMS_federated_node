from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.backend import BackendAPI
from app.definitions.sensors.git.base import GitAPIFactory
from app.definitions.sensors.git.pr_ingest import PullRequestIngestSensor

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


SENSORS = [
    git_pull_request_ingest_sensor,
]

JOBS = []
