"""
Commands that open a pull request in the Gitea trigger repo for the sensor to find. Each
step is its own command; `open-pr` runs them in order. The branch name is the one handle
that ties the steps together: the file and the PR title are derived from it.
"""

import json
import logging
import time
from datetime import datetime, timezone

import click
from pydantic import Field

from fncli.cmds.common import (
    DagsterConfig,
    TriggerRepoConfig,
    build_backend_api,
    build_gitea_api,
)
from fncli.cmds.project import find_project
from fncli.cmds.repository import init_gitea_repo
from fncli.cmds.sensor import SENSORS
from fncli.cmds.verify import Report, verify_task
from fncli.dagster.models import TriggerState
from fncli.dagster.sensors import DagsterAPI

logger = logging.getLogger("pr")

# What the sensor makes of the pull request: a task (watched), ignore it (unwatched, the
# file is outside the watch_dir) or reject it (invalid, the spec does not validate).
KINDS = ["watched", "unwatched", "invalid"]

POLL_SECONDS = 3
# Dagster's run statuses that end a task's run.
RUN_DONE = ["SUCCESS", "FAILURE", "CANCELED"]


class PrConfig(TriggerRepoConfig):
    pr_image: str = Field(default="busybox:latest", alias="TEST_PR_IMAGE")

    @property
    def repo_path(self) -> str:
        return f"{self.gitea_admin_user}/{self.repo}"


branch_option = click.option(
    "--branch", required=True, help="The PR's branch, as printed by create-gitea-branch."
)


def new_branch_name() -> str:
    """Unique per run, so every command can be re-run."""
    return f"pr-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def file_for(config: PrConfig, branch: str, kind: str) -> tuple[str, str]:
    """The path and content of the one new file a PR of that kind carries."""
    if kind == "unwatched":
        return f"docs/{branch}.md", f"# {branch}\n\nNot a spec: outside the watch_dir.\n"
    spec = {"name": branch, "image": config.pr_image}
    if kind == "invalid":
        # PullRequestSpec forbids unknown fields
        spec["unknown_field"] = True
    return f"{config.watch_dir}{branch}.json", json.dumps({"spec": spec}, indent=2) + "\n"


@click.command("create-gitea-branch")
@click.option("--branch", default=None, help="Branch name. Default: unique, from the time.")
def create_gitea_branch_command(branch):
    """Create a branch off the trigger repo's default branch."""
    config = PrConfig()
    branch = branch or new_branch_name()
    gitea_api = build_gitea_api(config)
    gitea_repo = init_gitea_repo(config, gitea_api)
    gitea_api.create_branch(config.repo_path, branch, gitea_repo["default_branch"])
    logger.info(f"Created branch {branch}")


@click.command("commit-gitea-file")
@branch_option
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
def commit_gitea_file_command(branch, kind):
    """Commit one new file to the branch, of a kind that decides what the sensor does."""
    config = PrConfig()
    file_path, content = file_for(config, branch, kind)
    build_gitea_api(config).create_file(
        config.repo_path, file_path, content, message=f"Add {file_path}", branch=branch
    )
    logger.info(f"Committed {kind} file {file_path} to {branch}")


@click.command("create-gitea-pr")
@branch_option
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
def create_gitea_pr_command(branch, kind):
    """Open a PR from the branch into the trigger repo's default branch."""
    config = PrConfig()
    gitea_api = build_gitea_api(config)
    gitea_repo = init_gitea_repo(config, gitea_api)
    pr = gitea_api.create_pull_request(
        config.repo_path,
        head_branch=branch,
        base_branch=gitea_repo["default_branch"],
        title=f"{kind} {branch}",
        body=f"A {kind} pull request, opened by fncli",
    )
    logger.info(f"Opened PR #{pr['number']}: {pr['html_url']}")
    return pr


def stuck_sensors(dagster_api: DagsterAPI, stage: str) -> list[str]:
    """The sensors of the stage the PR is stuck at that are not running."""
    return [
        name
        for name in SENSORS[stage]
        if dagster_api.get_sensor_state(name)["status"] != "RUNNING"
    ]


def watch_pr(config: PrConfig, number: int, timeout: int):
    """
    Print each change of the PR in the backend, then of its task and the task's run, until
    one ends or the timeout. When the run ends, print the verify-task report. Exits 1 on a
    REJECTED PR, a failed verification (which a failed or canceled run is) or a timeout.
    """
    backend_api = build_backend_api(config)
    dagster_api = DagsterAPI(DagsterConfig().dagster_url)
    project = find_project(config, backend_api)
    repo = backend_api.find_repository(config.repo_uri, project.id)
    seen = {}
    stage = "ingest"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = {}
        pr = next((p for p in backend_api.get_pull_requests(repo.id) if p.number == number), None)
        run = None
        if pr is None:
            lines["pr"] = "PR: waiting for ingest"
        else:
            cause = f" ({pr.state_cause})" if pr.state_cause else ""
            lines["pr"] = f"PR: {pr.state.value}{cause}"
            stage = "evaluate"
        if pr and pr.state == TriggerState.YIELDED:
            stage = "launcher"
            task = backend_api.get_task(pr.task_id)
            lines["task"] = f"Task {task.id}: {task.status}"
            run = dagster_api.get_task_run(task.id)
            if run:
                stage = "status"
                lines["run"] = f"Run {run['runId']}: {run['status']}"
        for key, line in lines.items():
            if seen.get(key) != line:
                seen[key] = line
                logger.info(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        if pr and pr.state == TriggerState.IGNORED:
            return
        if pr and pr.state == TriggerState.REJECTED:
            raise click.exceptions.Exit(1)
        if run and run["status"] in RUN_DONE:
            report = Report()
            verify_task(report, backend_api, dagster_api, repo.id, number)
            report.echo()
            raise click.exceptions.Exit(int(report.failed > 0))
        time.sleep(POLL_SECONDS)
    logger.info(f"Timed out after {timeout}s, last seen: {list(seen.values())}")
    logger.info(f"Sensors not running at the {stage} stage: {stuck_sensors(dagster_api, stage)}")
    raise click.exceptions.Exit(1)


watch_option = click.option(
    "--watch", is_flag=True, help="After merging, follow the PR, its task and run until the end."
)
timeout_option = click.option(
    "--timeout", default=300, show_default=True, help="Seconds --watch waits before giving up."
)


@click.command("merge-gitea-pr")
@click.option("--number", required=True, type=int, help="The PR's number.")
@watch_option
@timeout_option
def merge_gitea_pr_command(number, watch, timeout):
    """Merge a PR in the trigger repo, which is what makes the sensor pick it up."""
    config = PrConfig()
    build_gitea_api(config).merge_pull_request(config.repo_path, number)
    logger.info(f"Merged PR #{number}")
    if watch:
        watch_pr(config, number, timeout)


COMMANDS = [
    create_gitea_branch_command,
    commit_gitea_file_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
]
