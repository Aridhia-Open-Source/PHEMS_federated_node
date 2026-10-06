"""
verify-project: a read-only check of the test project, as a report. The backend's
healthcheck does the repo and token checks (it reaches each repo with its stored token), so
this adds only what the healthcheck leaves out: the dataset. Nothing is created or changed.
"""

import click

from fncli.cmds.common import DatasetConfig, ProjectConfig, build_backend_api


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


@click.command("verify-project")
def verify_project_command():
    """Check, read-only, the test project: its healthcheck and its dataset. Exits 1 on a failure."""
    report = Report()
    verify_project(report, ProjectConfig(), DatasetConfig())
    report.echo()
    if report.failed:
        raise click.exceptions.Exit(1)


COMMANDS = [verify_project_command]
