from typing import cast

import dagster as dg
from dagster import (
    OpExecutionContext as OpExecCtx,
    RunStatusSensorContext,
)

from app.backend import BackendAPI
from app.utils import BackendAdapter, BackendSession
from app.github import GithubAPI, GithubClient
from app.config import GithubTransferConfig, BackendConfig, GithubConfig
from app.definitions.sensors.github.pr_ingest import PullRequestIngestSensor
from app.definitions.sensors.github.pr_trigger import PullRequestTriggerSensor
from app.definitions.sensors.github.pr_status import PullRequestStatusSensor
from app.definitions.sensors.github.transfer_op import GithubTransferOperation
from app.definitions.sensors.github.comment_op import GithubCommentOperation
from app.definitions.jobs import k8s_pipes_job

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
def pull_request_ingest_sensor(context: OpExecCtx):
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
def pull_request_trigger_sensor(context: OpExecCtx):
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


@dg.op(
    config_schema={
        "pr_number": dg.Field(str),
        "parent_run_id": dg.Field(str),
        "repo_uri": dg.Field(str),
    },
)
def github_pr_comment_op(context: OpExecCtx):
    """Add success comment to original PR."""
    github_config = GithubConfig()
    github_client = GithubClient(
        token=github_config.token,
        base_uri=github_config.base_uri
    )
    github_api = GithubAPI(github_client)
    operation = GithubCommentOperation(context, github_api)
    return operation()


@dg.job
def github_pr_comment_job():
    """Job to add success comment to original PR."""
    github_pr_comment_op()



@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.QUEUED,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_queued_sensor(context: RunStatusSensorContext):
    run = context.dagster_run
    if run.tags.get("trigger") != "github":
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
        {"status": "QUEUED"}
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.STARTED,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_started_sensor(context: RunStatusSensorContext):
    run = context.dagster_run
    if run.tags.get("trigger") != "github":
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
        {"status": "STARTED"}
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    request_job=github_transfer_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_success_sensor(context: RunStatusSensorContext):
    run = context.dagster_run
    supported_triggers = ['github']
    trigger = run.tags.get("trigger") or 'null'
    if trigger not in supported_triggers:
        yield dg.SkipReason(f"Unsupported Trigger - {trigger}")
        return

    backend_config = BackendConfig()
    backend_adapter = BackendAdapter(
        base_url=backend_config.uri,
        username=backend_config.user,
        password=backend_config.password
    )
    backend_session = BackendSession(adapter=backend_adapter)
    backend_api = BackendAPI(session=backend_session)

    pr_number = run.tags["pr_number"]
    repo_id = run.tags["repo_id"]
    repo_uri = run.tags["repo_uri"]

    backend_api.patch_pull_request(int(repo_id), int(pr_number), {"status": "SUCCESS"})

    yield dg.RunRequest(
        run_key=f"{pr_number}-transfer",
        tags={
            "trigger": "github_transfer",
            "pr_number": pr_number,
            "parent_run_id": run.run_id,
        },
        run_config={
            "ops": {
                "github_transfer_op": {
                    "config": {
                        "parent_run_id": run.run_id,
                        "pr_number": pr_number,
                        "repo_uri": repo_uri,
                    }
                }
            }
        },
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_failure_sensor(context: RunStatusSensorContext):
    run = context.dagster_run
    if run.tags.get("trigger") != "github":
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
        {"status": "FAILURE"}
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.CANCELED,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_cancelled_sensor(context: RunStatusSensorContext):
    run = context.dagster_run
    if run.tags.get("trigger") != "github":
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
        {"status": "CANCELLED"}
    )


# @dg.run_status_sensor(
#     run_status=dg.DagsterRunStatus.SUCCESS,
#     default_status=dg.DefaultSensorStatus.RUNNING,
#     monitored_jobs=[github_transfer_job],
#     request_job=github_pr_comment_job,
#     minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
# )
# def github_transfer_success_comment_sensor(context: RunStatusSensorContext):
#     """Trigger PR comment after successful transfer job."""
#     run = context.dagster_run

#     if not run.tags.get("trigger") == "github":
#         yield dg.SkipReason("Run not triggered from github")
#         return

#     if not run.tags.get("pr_number"):
#         yield dg.SkipReason("Missing pr_number tag")
#         return

#     pr_number = run.tags["pr_number"]
#     parent_run_id = run.tags.get("parent_run_id", "")
#     repo_uri = run.tags.get("repo_uri", "")

#     context.log.info(f"Triggering PR comment for PR #{pr_number}")

#     yield dg.RunRequest(
#         run_key=f"{pr_number}-comment",
#         tags={
#             "trigger": "github",
#             "pr_number": pr_number,
#             "parent_run_id": parent_run_id,
#         },
#         run_config={
#             "ops": {
#                 "github_pr_comment_op": {
#                     "config": {
#                         "pr_number": pr_number,
#                         "parent_run_id": parent_run_id,
#                         "repo_uri": repo_uri,
#                     }
#                 }
#             }
#         },
#     )


SENSORS = [
    pull_request_ingest_sensor,
    pull_request_trigger_sensor,
    task_queued_sensor,
    task_started_sensor,
    task_success_sensor,
    task_failure_sensor,
    task_cancelled_sensor,
    # github_transfer_success_comment_sensor,
]

JOBS = [github_transfer_job, github_pr_comment_job]
