"""
verify-project: a read-only check of the test project, as a report. The backend's
healthcheck does the repo and token checks (it reaches each repo with its stored token), so
this adds only what the healthcheck leaves out: the dataset. Nothing is created or changed.
"""

from dataclasses import dataclass

import click

from fncli.cmds.common import (
    DagsterConfig,
    DatasetConfig,
    ProjectConfig,
    TriggerRepoConfig,
    build_backend_api,
    to_host_url,
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

    def link(self, name, url):
        """A URL to open, not a check: counts as neither passed nor failed."""
        self.rows.append(("link", name, url))

    @property
    def failed(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == "FAIL")

    def echo(self, summary: bool = True, indent: str = ""):
        for status, name, detail in self.rows:
            click.echo(f"{indent}[{status:>4}] {name}" + (f"  ({detail})" if detail else ""))
        if not summary:
            return
        passed = sum(1 for status, _, _ in self.rows if status == "ok")
        skipped = sum(1 for status, _, _ in self.rows if status == "SKIP")
        click.echo(f"\n{passed} passed, {self.failed} failed, {skipped} skipped")


@dataclass
class Links:
    """Builds the URLs the reports print, as they open from the host."""
    gitea_url: str
    dagster_url: str
    # owner/repo of the trigger repo, from its stored uri
    repo_path: str

    def trigger_pr(self, number: int) -> str:
        return to_host_url(f"{self.gitea_url}/{self.repo_path}/pulls/{number}")

    def run(self, run_id: str) -> str:
        return to_host_url(f"{self.dagster_url}/runs/{run_id}")


def require(value, what: str):
    if value is None:
        raise RuntimeError(f"{what} not found")
    return value


def exactly_one(results: list):
    if len(results) != 1:
        raise RuntimeError(f"expected 1 result, found {len(results)}")
    return results[0]


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


def verify_task(
    report: Report, backend_api, dagster_api: DagsterAPI, links: Links, repo_id: int, number: int
):
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
    report.link("Trigger PR", links.trigger_pr(number))
    verify_pr(report, backend_api, dagster_api, links, pr)


def verify_pr(report: Report, backend_api, dagster_api: DagsterAPI, links: Links, pr):
    """The checks for one PR already fetched: its task in the backend against its Dagster run."""
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
    if run is not None:
        report.link("Dagster run", links.run(run["runId"]))
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
    if run["status"] == "SUCCESS":
        verify_delivery(report, backend_api, pr.task_id)


def verify_delivery(report: Report, backend_api, task_id: int):
    """A succeeded task's results are delivered: one TaskResult, DELIVERED, with a commit and a results PR."""
    results = report.check(
        f"Task {task_id} has one results delivery: GET /tasks/{task_id}/results",
        lambda: exactly_one(backend_api.get_task_results(task_id)),
        lambda r: f"{r.status}, attempts {r.attempts}",
    )
    if results is None:
        return
    report.record(
        results.status == "DELIVERED",
        "Results were DELIVERED",
        f"{results.status}" + (f": {results.error}" if results.error else ""),
    )
    report.record(results.commit_sha is not None, "Delivery has a commit_sha", str(results.commit_sha))
    report.record(
        results.number is not None and results.url is not None,
        "Delivery has a results PR",
        f"#{results.number}, {results.merge_status}",
    )
    if results.url is not None:
        report.link("Results PR", to_host_url(results.url))


def verify_repo(
    backend_api, dagster_api: DagsterAPI, links: Links, repo_id: int, tail: int | None
) -> int:
    """
    Print a report per PR of the trigger repo, the last `tail` by number if given, and a
    summary. Returns how many checks failed. A PR the sensor ignored or rejected has no task
    to check, which is the right outcome for it. One still UNKNOWN has not been evaluated.
    """
    prs = sorted(backend_api.get_pull_requests(repo_id), key=lambda pr: pr.number)
    if tail:
        prs = prs[-tail:]
    if not prs:
        click.echo("No pull requests in the repo")
        return 1
    failed = 0
    for pr in prs:
        report = Report()
        report.link("Trigger PR", links.trigger_pr(pr.number))
        if pr.state in (TriggerState.IGNORED, TriggerState.REJECTED):
            report.record(True, f"PR was {pr.state.value}, so no task is expected", pr.state_cause or "")
        elif pr.state == TriggerState.UNKNOWN:
            report.record(False, "PR was evaluated", "still UNKNOWN, the evaluate sensor has not run on it")
        else:
            verify_pr(report, backend_api, dagster_api, links, pr)
        click.echo(f"PR #{pr.number}: {pr.title}")
        report.echo(summary=False, indent="  ")
        failed += report.failed
    click.echo(f"\n{len(prs)} PRs checked, {failed} checks failed")
    return failed


@click.command("verify-repo")
@click.option("--tail", type=int, default=None, help="Only check the last N PRs, by number. Default: all.")
def verify_repo_command(tail):
    """Check, read-only, that every merged PR of the trigger repo ran in Dagster and the backend agrees. Exits 1 on a failure."""
    config = TriggerRepoConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    repo = backend_api.find_repository(config.repo_uri, project.id)
    dagster_url = DagsterConfig().dagster_url
    links = Links(config.gitea_url, dagster_url, repo.repo_path)
    if verify_repo(backend_api, DagsterAPI(dagster_url), links, repo.id, tail):
        raise click.exceptions.Exit(1)


@click.command("verify-project")
def verify_project_command():
    """Check, read-only, the test project: its healthcheck and its dataset. Exits 1 on a failure."""
    report = Report()
    verify_project(report, ProjectConfig(), DatasetConfig())
    report.echo()
    if report.failed:
        raise click.exceptions.Exit(1)


COMMANDS = [verify_project_command, verify_repo_command]
