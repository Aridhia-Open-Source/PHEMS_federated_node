from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.backend import BackendAPI
from app.config import DEFAULT_SENSOR_STATUS, MIN_SENSOR_INTERVAL_SECONDS
from app.definitions.sensors.git.base import GitAPIFactory
from app.definitions.sensors.git.ingest_job import ingest_pull_requests_job
from app.definitions.sensors.git.pr_ingest import PullRequestIngestSensor
from app.definitions.sensors.git.evaluate_job import evaluate_repository_pull_requests_job
from app.definitions.sensors.git.pr_evaluate import PullRequestEvaluateSensor


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api", "git_apis"},
    job=ingest_pull_requests_job,
)
def git_pull_request_ingest_sensor(context: OpExecCtx):
    """
    Sensor that polls the git provider for new merged pull requests in configured
    repositories and launches ingest_pull_requests_job for each repository that has some.

    Flow:
    1. Fetch configured repositories
    2. For each repo, build its api client and query the provider for merged PRs since
       the repo's cursor
    3. Request an ingest run for the repo if there are any; the job saves them as UNKNOWN
    """
    sensor = PullRequestIngestSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
    )
    yield from sensor()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api", "git_apis"},
    job=evaluate_repository_pull_requests_job,
)
def git_pull_request_evaluate_sensor(context: OpExecCtx):
    """
    Sensor that launches evaluate_repository_pull_requests_job for each trigger repository
    of an enabled project that has UNKNOWN pull requests, unless a run of it is in flight.
    """
    sensor = PullRequestEvaluateSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
    )
    yield from sensor()


SENSORS = [
    git_pull_request_ingest_sensor,
    git_pull_request_evaluate_sensor,
]

JOBS = [ingest_pull_requests_job, evaluate_repository_pull_requests_job]
