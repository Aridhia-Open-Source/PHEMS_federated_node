"""
verify-project: a read-only check of the test project, as a report. The backend's
healthcheck does the repo and token checks (it reaches each repo with its stored token), so
this adds only what the healthcheck leaves out: the dataset. Nothing is created or changed.
"""

import click

from fncli.cmds.common import (
    DagsterConfig,
    DatasetConfig,
    ProjectConfig,
    TriggerRepoConfig,
    build_backend_api,
)
from fncli.cmds.project import find_project
from fncli.dagster.models import TriggerState
from fncli.dagster.sensors import DagsterAPI

# The task status the run-status sensors give each Dagster run status.
RUN_TO_TASK_STATUS = {
    "QUEUED": "QUEUED",
    "STARTED": "RUNNING",
    "SUCCESS": "SUCCESS",
    "FAILURE": "FAILED",
    "CANCELED": "CANCELED",
}
TASK_JOB = "k8s_pipes_job"


class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, call, detail=lambda result: ""):
        """Run one check. A failure is recorded, not raised, so the rest still run."""
        try:
            result = call()
        except Exception as error:
            self.rows.append(("FAIL", name, str(error) or type(error).__name__))
            return None
        self.rows.append(("ok", name, detail(result)))
        return result

    def record(self, ok: bool, name: str, detail: str):
        self.rows.append(("ok" if ok else "FAIL", name, detail))

    def skip(self, name, reason):
        self.rows.append(("SKIP", name, reason))

    @property
    def failed(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == "FAIL")

    def echo(self):
        for status, name, detail in self.rows:
            click.echo(f"[{status:>4}] {name}" + (f"  ({detail})" if detail else ""))
        passed = sum(1 for status, _, _ in self.rows if status == "ok")
        skipped = sum(1 for status, _, _ in self.rows if status == "SKIP")
        click.echo(f"\n{passed} passed, {self.failed} failed, {skipped} skipped")


def require(value, what: str):
    if value is None:
        raise RuntimeError(f"{what} not found")
    return value


def record_repo_health(report: Report, kind: str, repo: dict):
    """One healthcheck repo entry: reachable with its stored token or not."""
    check = repo["health_check"]
    report.record(
        repo["status"] == "ok",
        f"{kind} repo reachable with its token: {repo['uri']}",
        f"{check['message']}, {check['latency_ms']} ms",
    )


def verify_project(report: Report, config: ProjectConfig, dataset_config: DatasetConfig):
    backend_api = report.check("Backend login: POST /login", lambda: build_backend_api(config))
    if backend_api is None:
        report.skip("everything else", "no backend login")
        return

    project = report.check(
        "Project exists: GET /projects",
        lambda: require(backend_api.find_project(config.project_name), config.project_name),
        lambda p: f"id {p.id}",
    )
    if project is None:
        report.skip("everything else", "no project, run setup-project first")
        return

    health = report.check(
        f"Project healthcheck: GET /projects/{project.id}/healthcheck",
        lambda: backend_api.get_project_healthcheck(project.id),
        lambda h: f"status {h['status']}, enabled {h['enabled']}",
    )
    if health is not None:
        report.record(health["enabled"], "Project is enabled", "")
        if not health["trigger_repositories"]:
            report.record(False, "Trigger repo is registered", "none on the project")
        for repo in health["trigger_repositories"]:
            record_repo_health(report, "Trigger", repo)
            report.record(True, "Trigger repo pull requests stored", f"{repo['pr_count']}")
        if health["results_repository"] is None:
            report.record(False, "Results repo is registered", "none on the project")
        else:
            record_repo_health(report, "Results", health["results_repository"])

    dataset = report.check(
        f"Dataset exists: GET /datasets ({dataset_config.dataset_name})",
        lambda: require(
            backend_api.find_dataset(dataset_config.dataset_name, project.id),
            dataset_config.dataset_name,
        ),
        lambda d: f"id {d.id}",
    )
    if dataset is not None:
        report.check(
            f"Dataset fetch: GET /datasets/{dataset.id}", lambda: backend_api.get_dataset(dataset.id)
        )
        report.check(
            f"Dataset secret exists: GET /projects/{project.id}/secrets",
            lambda: backend_api.get_secret(project.id, dataset.secret.label),
            lambda s: f"{s['key']} in {s['namespace']}",
        )


def verify_task(report: Report, backend_api, dagster_api: DagsterAPI, repo_id: int, number: int):
    """Compare a merged PR's task in the backend with its run in Dagster."""
    pr = report.check(
        f"PR #{number} is in the backend: GET /trigger_repositories/{repo_id}/pull_requests",
        lambda: require(
            next((p for p in backend_api.get_pull_requests(repo_id) if p.number == number), None),
            f"PR #{number}",
        ),
        lambda p: p.state.value,
    )
    if pr is None:
        return
    cause = f"{pr.state.value}, {pr.state_cause}" if pr.state_cause else pr.state.value
    report.record(pr.state == TriggerState.YIELDED, "PR was YIELDED, so it has a task", cause)
    if pr.state != TriggerState.YIELDED:
        return

    task = report.check(
        f"Task {pr.task_id} is in the backend: GET /tasks/{pr.task_id}",
        lambda: backend_api.get_task(pr.task_id),
        lambda t: f"{t.status}, attempt {t.attempt}",
    )
    run = report.check(
        f"Task {pr.task_id} has a Dagster run: runs tagged task_id={pr.task_id}",
        lambda: require(dagster_api.get_task_run(pr.task_id), "run"),
        lambda r: f"{r['runId']}, {r['status']}",
    )
    if task is None or run is None:
        return

    tags = {tag["key"]: tag["value"] for tag in run["tags"]}
    expected = RUN_TO_TASK_STATUS[run["status"]]
    report.record(run["jobName"] == TASK_JOB, f"Run is a {TASK_JOB}", run["jobName"])
    report.record(
        task.status == expected,
        "Task status matches the run",
        f"task {task.status}, run {run['status']} (expected {expected})",
    )
    report.record(
        task.dagster_run_id == run["runId"],
        "Task holds the run's id",
        f"task {task.dagster_run_id}, run {run['runId']}",
    )
    report.record(
        str(task.attempt) == tags.get("attempt"),
        "Task attempt matches the run's attempt tag",
        f"task {task.attempt}, run {tags.get('attempt')}",
    )
    if expected != "QUEUED":
        report.record(task.started_at is not None, "Task has started_at", str(task.started_at))
    if expected in ("SUCCESS", "FAILED", "CANCELED"):
        report.record(task.completed_at is not None, "Task has completed_at", str(task.completed_at))
    report.record(run["status"] == "SUCCESS", "Run succeeded", run["status"])


@click.command("verify-task")
@click.option("--number", required=True, type=int, help="The merged PR's number.")
def verify_task_command(number):
    """Check, read-only, that a merged PR's task ran in Dagster and the backend agrees. Exits 1 on a failure."""
    config = TriggerRepoConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    repo = backend_api.find_repository(config.repo_uri, project.id)
    report = Report()
    verify_task(report, backend_api, DagsterAPI(DagsterConfig().dagster_url), repo.id, number)
    report.echo()
    if report.failed:
        raise click.exceptions.Exit(1)


@click.command("verify-project")
def verify_project_command():
    """Check, read-only, the test project: its healthcheck and its dataset. Exits 1 on a failure."""
    report = Report()
    verify_project(report, ProjectConfig(), DatasetConfig())
    report.echo()
    if report.failed:
        raise click.exceptions.Exit(1)


COMMANDS = [verify_project_command, verify_task_command]
