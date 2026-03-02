import os
import json
import logging
from datetime import datetime as dt
from datetime import timezone as tz
from datetime import timedelta as td

import dagster as dg

from app.definitions.jobs import k8s_pipes_job
from app.github import GithubClient

ARTIFACT_MOUNT_BASE_PATH = os.environ["DAGSTER_ARTIFACT_MOUNT_PATH"]
GH_TOKEN = os.environ["GH_TOKEN"]
GH_OWNER = os.environ['GH_OWNER']
GH_REPO = os.environ['GH_REPO']
GH_BASE_BRANCH = os.environ['GH_BASE_BRANCH']
GH_WATCH_DIR = os.environ['GH_WATCH_DIR']
MNT_BASE_PATH = os.environ['MNT_BASE_PATH']


logger = logging.getLogger(__name__)


# def utc_now():
#     return dt.now(tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# FIXME: Temp dev hack to set initial cursor to 24hrs ago to pick up recent PRs
def utc_now():
    return (dt.now(tz.utc) - td(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

@dg.op(
    config_schema={
        "run_id": str,
    }
)
def transfer_op(context: dg.OpExecutionContext):
    source_run_id = context.op_config["run_id"]
    source_path = f"{ARTIFACT_MOUNT_BASE_PATH}/{source_run_id}"
    source_files = os.listdir(source_path)
    context.log.info(f"Files in source path: {source_files}")
    return source_files


@dg.job
def transfer_job():
    transfer_op()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    request_job=transfer_job,
)
def k8s_pipes_sensor(context: dg.RunStatusSensorContext):
    run = context.dagster_run

    return dg.RunRequest(
        run_key=run.run_id,
        run_config={
            "ops": {
                "transfer_op": {
                    "config": {
                        "run_id": run.run_id,
                    }
                }
            }
        },
    )


@dg.sensor(
    job=k8s_pipes_job,
    minimum_interval_seconds=5,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def github_pull_request_polling_sensor(context):
    client = GithubClient(
        owner=GH_OWNER,
        repo=GH_REPO,
        token=GH_TOKEN,
        base_branch=GH_BASE_BRANCH,
    )

    if not context.cursor:
        context.update_cursor(utc_now())
        yield dg.SkipReason("Initializing Cursor")
        return

    pullreqs = client.get_new_merged_pulls(
        cursor=context.cursor,
        watch_dir=os.environ["GH_WATCH_DIR"],
        per_page=100,
    )

    if not pullreqs:
        yield dg.SkipReason("No watched PRs merged since last check")
        return

    newest_merged_at = max(pr["merged_at"] for pr in pullreqs)
    context.update_cursor(newest_merged_at)

    for pr in pullreqs:
        if len(pr["watched_files"]) != 1:
            # TODO: Handle multiple watched files per PR
            logger.error("Multiple request files in single PR not supported")
            continue

        filename = pr['watched_files'][0]
        content = client.get_file_contents(filename, ref=pr['merge_commit_sha'])
        data = json.loads(content)
        docker_image = data['spec']['docker_image']

        yield dg.RunRequest(
            run_key=f"{pr['number']}-{pr['merged_at']}",
            run_config={
                "ops": {
                    "k8s_pipes_op": {
                        "config": {
                            "docker_image": docker_image,
                        }
                    }
                }
            },
        )


sensors = [
    k8s_pipes_sensor,
    github_pull_request_polling_sensor,
]
