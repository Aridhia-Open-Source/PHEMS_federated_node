import os
import json
from datetime import datetime as dt
from datetime import timezone as tz
from datetime import timedelta as td

import dagster as dg
from dagster_k8s import PipesK8sClient
from dagster import OpExecutionContext as OpExecCtx

from app.definitions.jobs import k8s_pipes_job
from app.definitions.pipes import K8sPipe
from app.github import GithubClient

# =============================================================================
# TODO: PRODUCTION HARDENING
# =============================================================================
#
# - Add PR comments on Dagster run START / SUCCESS / FAILURE
# - Implement failure run_status_sensor to notify originating PR
# - Add explicit idempotency guard (cursor tuple or results manifest)
# - Verify prevention of duplicate results branches / pushes
# - Add concurrency limits for user-triggered jobs
# - Add structured Dagster run tags for governance (e.g. type=user/internal)
# - Document full event flow (PR → sensor → job → transfer → results)
# - Add README section explaining key design tradeoffs
# - Document operational assumptions (cursor semantics, retry behavior, artifact model)
#
# =============================================================================

MIN_SENSOR_INTERVAL_SECONDS = 10


# TODO: convert to pydantic settings model with validation
class GithubSensorConfig:
    _REQUIRED_VARIABLES = [
        "DAGSTER_ARTIFACT_MOUNT_PATH",
        "GH_TRANSFER_DOCKER_IMAGE",
        "GH_OWNER",
        "GH_REPO",
        "GH_TOKEN",
        "GH_RESULTS_DIR",
        "GH_BASE_BRANCH",
        "GH_WATCH_DIR",
    ]

    @property
    def default_sensor_status(self):
        if self.enabled:
            return dg.DefaultSensorStatus.RUNNING
        return dg.DefaultSensorStatus.STOPPED

    def __init__(self):
        self.enabled = os.environ.get("GH_SENSORS_ENABLED", "").lower() == "true"
        if self.enabled:
            self._validate_env()

        self.artifact_mount_path = os.environ.get("DAGSTER_ARTIFACT_MOUNT_PATH", "")
        self.transfer_docker_image = os.environ.get("GH_TRANSFER_DOCKER_IMAGE", "")
        self.owner = os.environ.get("GH_OWNER", "")
        self.repo = os.environ.get("GH_REPO", "")
        self.token = os.environ.get("GH_TOKEN", "")
        self.results_dir = os.environ.get("GH_RESULTS_DIR", "")
        self.base_branch = os.environ.get("GH_BASE_BRANCH", "")
        self.watch_dir = os.environ.get("GH_WATCH_DIR", "")

    def _validate_env(self):
        if missing := [v for v in self._REQUIRED_VARIABLES if not os.environ.get(v)]:
            raise EnvironmentError(f"GH sensors enabled but missing: {missing}")


gh_config = GithubSensorConfig()


def utc_now():
    return (dt.now(tz.utc) + td(days=0)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dg.op(
    config_schema={
        "docker_image": dg.Field(str),
        "parent_run_id": dg.Field(str),
        "pr_number": dg.Field(str),
    }
)
def github_transfer_op(context: OpExecCtx, k8s_pipes_client: PipesK8sClient) -> dg.Output:
    env = {
        "GH_OWNER": gh_config.owner,
        "GH_REPO": gh_config.repo,
        "GH_TOKEN": gh_config.token,
        "GH_BASE_BRANCH": gh_config.base_branch,
        "GH_RESULTS_DIR": gh_config.results_dir,
        "MNT_BASE_PATH": gh_config.artifact_mount_path,
        "PARENT_RUN_ID": context.op_config["parent_run_id"],
        "PR_NUMBER": context.op_config["pr_number"],
    }
    pipe = K8sPipe(client=k8s_pipes_client, context=context, ext_env=env)
    return pipe().output


@dg.job
def github_transfer_job():
    github_transfer_op()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    request_job=github_transfer_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def github_run_success_transfer_sensor(context: dg.RunStatusSensorContext):
    run = context.dagster_run
    context.log.info("github_run_success_transfer_sensor...")
    context.log.info(f"Run tags: {run.tags}")

    if not run.tags.get('trigger') == 'github':
        context.log.error("Skipping - Run not triggered by GitHub")
        yield dg.SkipReason("Run not triggered by GitHub")
        return

    if not run.tags.get('pr_number'):
        yield dg.SkipReason("Missing pr_number tag")
        context.log.error("Skipping - missing pr_number tag")
        return

    config = {
        'docker_image': gh_config.transfer_docker_image,
        'pr_number': run.tags["pr_number"],
        'parent_run_id': run.run_id,
    }

    context.log.info(f"Triggering GitHub transfer - {config}")

    yield dg.RunRequest(
        run_key=run.run_id,
        tags={
            "type": "internal",
            "trigger": "github_transfer",
            "pr_number": run.tags["pr_number"],
            "parent_run_id": run.run_id,
        },
        run_config={
            "ops": {
                "github_transfer_op": {
                    "config": config
                }
            }
        },
    )


@dg.sensor(
    job=k8s_pipes_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def github_pull_request_polling_sensor(context):
    client = GithubClient(
        owner=gh_config.owner,
        repo=gh_config.repo,
        token=gh_config.token,
        base_branch=gh_config.base_branch,
    )

    if not context.cursor:
        context.update_cursor(utc_now())
        yield dg.SkipReason("Initializing Cursor")
        return

    pullreqs = client.get_new_merged_pulls(
        cursor=context.cursor,
        watch_dir=gh_config.watch_dir,
        per_page=100,
    )

    if not pullreqs:
        yield dg.SkipReason("No watched PRs merged since last check")
        return

    # FIXME: Edge case race condition - multiple PRs merged at same time?
    newest_merged_at = max(pr["merged_at"] for pr in pullreqs)
    context.update_cursor(newest_merged_at)

    for pr in pullreqs:
        if len(pr["watched_files"]) != 1:
            # TODO: Handle multiple watched files per PR
            context.log.error("Multiple request files in single PR not supported")
            continue

        filename = pr['watched_files'][0]
        content = client.get_file_contents(filename, ref=pr['merge_commit_sha'])
        data = json.loads(content)

        spec = data['spec']
        docker_image = spec['docker_image']
        env = spec.get('env', {})

        yield dg.RunRequest(
            run_key=f"{pr['number']}-{pr['merged_at']}",
            tags={
                "type": "user",
                "trigger": "github",
                "pr_number": str(pr["number"]),
            },
            run_config={
                "ops": {
                    "k8s_pipes_op": {
                        "config": {
                            "docker_image": docker_image,
                            "env": env
                        }
                    }
                }
            },
        )


@dg.op(
    config_schema={
        "parent_run_id": dg.Field(str),
        "pr_number": dg.Field(str),
    }
)
def github_pr_comment_op(context: OpExecCtx):
    pr_number = context.op_config["pr_number"]
    parent_run_id = context.op_config["parent_run_id"]
    if not pr_number or not parent_run_id:
        context.log.error("Skipping - missing required tags")
        return

    body = f"Success - #{parent_run_id}"
    context.log.info(f"Adding GH PR comment - run_id: {parent_run_id}, pr: {pr_number}")
    client = GithubClient(
        owner=gh_config.owner,
        repo=gh_config.repo,
        token=gh_config.token,
        base_branch=gh_config.base_branch,
    )
    client.add_pull_request_comment(pr_number, body)


@dg.job
def github_pr_comment_job():
    github_pr_comment_op()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[github_transfer_job],
    request_job=github_pr_comment_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def github_transfer_success_sensor(context: dg.RunStatusSensorContext):
    run = context.dagster_run
    context.log.info("github_transfer_success_sensor...")
    context.log.info(f"Run tags: {run.tags}")

    parent_run_id = run.tags["parent_run_id"]
    pr_number = run.tags["pr_number"]

    yield dg.RunRequest(
        run_key=run.run_id,
        tags={
            "type": "internal",
            "trigger": "github_pr_comment",
            "pr_number": pr_number,
            "parent_run_id": parent_run_id,
        },
        run_config={
            "ops": {
                "github_pr_comment_op": {
                    "config": {
                        "parent_run_id": parent_run_id,
                        "pr_number": pr_number,
                    }
                }
            }
        },
    )


sensors = [
    github_pull_request_polling_sensor,
    github_run_success_transfer_sensor,
    github_transfer_success_sensor,
]

sensor_jobs = [
    github_transfer_job,
    github_pr_comment_job,
]
