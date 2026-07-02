import os
import json
import shutil
import subprocess
import tempfile
import zipfile
import requests
from pathlib import Path
from datetime import datetime as dt
from datetime import timezone as tz
from datetime import timedelta as td

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.definitions.jobs import k8s_pipes_job
from app.github import GithubClient, GithubAPI, GithubRepo

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
# - Review github api client for optimizations and edge cases
# =============================================================================

MIN_SENSOR_INTERVAL_SECONDS = 10


# TODO: convert to pydantic settings model with validation
class GithubSensorConfig:
    _REQUIRED_VARIABLES = [
        "DAGSTER_ARTIFACT_MOUNT_PATH",
        "GH_TOKEN",
        "GH_RESULTS_DIR",
        "GH_BASE_BRANCH",
        "GH_WATCH_DIR",
        "WEBSERVER_URL",
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
        self.token = os.environ.get("GH_TOKEN", "")
        self.results_dir = os.environ.get("GH_RESULTS_DIR", "")
        self.base_branch = os.environ.get("GH_BASE_BRANCH", "main")
        self.watch_dir = os.environ.get("GH_WATCH_DIR", "")
        self.webserver_url = os.environ.get("WEBSERVER_URL", "").rstrip("/")

    def _validate_env(self):
        if missing := [v for v in self._REQUIRED_VARIABLES if not os.environ.get(v)]:
            raise EnvironmentError(f"GH sensors enabled but missing: {missing}")


gh_config = GithubSensorConfig()


def utc_now():
    return (dt.now(tz.utc) + td(days=0)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# GitHub transfer helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: str | None = None) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


def _zip_directory(src: Path, dest_zip: Path) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in src.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src))


def _remote_branch_exists(owner: str, repo: str, branch: str, token: str) -> bool:
    resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    return resp.status_code == 200


def _create_github_pr(
    owner: str, repo: str, head: str, base: str,
    pr_number: str, parent_run_id: str, token: str,
) -> str:
    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        json={
            "title": f"PR{pr_number} - results",
            "body": f"Automated results for PR #{pr_number}, run {parent_run_id}",
            "head": head,
            "base": base,
        },
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    resp.raise_for_status()
    return resp.json()["html_url"]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@dg.op(
    config_schema={
        "parent_run_id": dg.Field(str),
        "pr_number": dg.Field(str),
        "repo_uri": dg.Field(str),
    }
)
def github_transfer_op(context: OpExecCtx) -> dg.Output:
    pr_number = context.op_config["pr_number"]
    parent_run_id = context.op_config["parent_run_id"]
    repo_uri = context.op_config["repo_uri"]  # "github.com/owner/repo"

    _, owner_repo = repo_uri.split("/", 1)
    owner, repo = owner_repo.split("/", 1)

    branch = f"{pr_number}-{parent_run_id}-results"
    repo_output_path = f"{gh_config.results_dir}/{pr_number}/{parent_run_id}"
    artifact_path = Path(gh_config.artifact_mount_path) / parent_run_id

    context.log.info(f"GitHub transfer starting - PR#{pr_number}, run {parent_run_id}")

    clone_dir = tempfile.mkdtemp(prefix="phems-transfer-")
    try:
        clone_url = f"https://{gh_config.token}@github.com/{owner}/{repo}.git"
        context.log.info(f"Cloning {owner}/{repo}")
        _git(["clone", "--depth=1", clone_url, clone_dir])
        _git(["-C", clone_dir, "config", "user.name", "phems-bot"])
        _git(["-C", clone_dir, "config", "user.email",
              "phem-federated-node@users.noreply.github.com"])
        _git(["-C", clone_dir, "fetch", "origin"])

        if _remote_branch_exists(owner, repo, branch, gh_config.token):
            raise Exception(f"Results branch {branch!r} already exists on remote")

        _git(["-C", clone_dir, "checkout", "-b", branch])

        output_dir = Path(clone_dir) / repo_output_path
        output_dir.mkdir(parents=True, exist_ok=True)

        context.log.info(f"Archiving {artifact_path}")
        _zip_directory(artifact_path, output_dir / "archive.zip")

        _git(["-C", clone_dir, "add", "."])
        _git(["-C", clone_dir, "commit", "-m",
              f"PR{pr_number} - {parent_run_id} - results"])
        _git(["-C", clone_dir, "push", "--set-upstream", "origin", branch])
        context.log.info("Results branch pushed")

        pr_url = _create_github_pr(
            owner, repo, branch, gh_config.base_branch, pr_number, parent_run_id, gh_config.token
        )
        context.log.info(f"Pull request created: {pr_url}")

    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)

    return dg.Output(
        value={"pr_url": pr_url, "branch": branch},
        metadata={"pr_url": pr_url, "branch": branch},
    )


@dg.job
def github_transfer_job():
    github_transfer_op()


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

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
        'pr_number': run.tags["pr_number"],
        'parent_run_id': run.run_id,
        'repo_uri': run.tags.get("repo_uri", ""),
    }

    context.log.info(f"Triggering GitHub transfer - {config}")

    yield dg.RunRequest(
        run_key=run.run_id,
        tags={
            "type": "internal",
            "trigger": "github_transfer",
            "pr_number": run.tags["pr_number"],
            "repo_id": run.tags.get("repo_id", ""),
            "repo_uri": run.tags.get("repo_uri", ""),
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
    repos_resp = requests.get(f"{gh_config.webserver_url}/repositories")
    repos_resp.raise_for_status()
    repos = repos_resp.json()

    if not repos:
        yield dg.SkipReason("No repositories configured")
        return

    gh = GithubAPI(client=GithubClient(token=gh_config.token))

    for repo in repos:
        repo_uri = repo["uri"].split("/", 1)[1]  # "github.com/org/repo" → "org/repo"
        new_prs = gh.get_merged_prs_after_number(
            repo_uri=repo_uri,
            base_branch=repo["base_branch"],
            pr_cursor=repo["pr_cursor"],
            watch_dir=gh_config.watch_dir,
        )

        if not new_prs:
            yield dg.SkipReason(f"No new PRs for {repo['uri']}")
            continue

        for pr in new_prs:
            if len(pr["watched_files"]) != 1:
                context.log.error("Multiple request files in single PR not supported")
                continue

            filename = pr["watched_files"][0]
            content = gh.get_file_contents(repo_uri, filename, ref=pr["merge_commit_sha"])
            spec = json.loads(content)["spec"]

            yield dg.RunRequest(
                run_key=f"{repo['id']}-{pr['number']}",
                tags={
                    "type": "user",
                    "trigger": "github",
                    "pr_number": str(pr["number"]),
                    "repo_id": str(repo["id"]),
                    "repo_uri": repo["uri"],
                },
                run_config={
                    "ops": {
                        "k8s_pipes_op": {
                            "config": {
                                "docker_image": spec["docker_image"],
                                "env": spec.get("args", {}),
                            }
                        }
                    }
                },
            )

        max_pr_number = max(pr["number"] for pr in new_prs)
        requests.patch(
            f"{gh_config.webserver_url}/repositories/{repo['id']}",
            json={"pr_cursor": max_pr_number, "polled_at": utc_now()},
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
    # TODO: wire up repo_uri from run tags so the correct repo gets the comment
    gh = GithubRepo(
        client=GithubClient(token=gh_config.token),
        uri="github.com/placeholder/placeholder",
        base_branch=gh_config.base_branch,
    )
    gh.add_pull_request_comment(pr_number, body)


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
