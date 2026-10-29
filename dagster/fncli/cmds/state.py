"""
Commands for the end-to-end suites (tests/e2e/README.md): look at the test project's state, and change the
state nexus-api's rules act on (project enabled and revoked, a project resource's enabled and revoked, a global resource's enabled and revoked),
plus a second project on the same global resources. Every write prints the HTTP status and body; `--expect STATUS` asserts
the status, which is how the suites check the 409 rules. Without it a status of 400 or more is a failure.
"""

import json
import logging

import click

from fncli.cmds.common import SECRET_CONFIGS, ProjectConfig, build_admin_backend_api, build_backend_api
from fncli.backend import FncliBackendAPI

logger = logging.getLogger("state")

KINDS = ("trigger", "results", "dataset", "secret")
BOOL = click.Choice(["true", "false"])


def call(api: FncliBackendAPI, method: str, path: str, **kwargs):
    return api.session.request(method, path, raise_for_status=False, **kwargs)


def body_of(response):
    try:
        return response.json() if response.content else None
    except ValueError:
        return response.text


def get(api: FncliBackendAPI, path: str, **params):
    response = call(api, "GET", path, params=params or None)
    if response.status_code >= 400:
        raise click.ClickException(f"GET {path} -> {response.status_code}: {response.text[:300]}")
    return body_of(response)


def find_project(api: FncliBackendAPI, name: str):
    project = api.find_project(name)
    if project is None:
        raise click.ClickException(f"Project {name} not found, run setup-project first")
    return project


def project_resources(api: FncliBackendAPI, project_id: int) -> dict:
    return {
        "trigger": get(api, f"/projects/{project_id}/repositories/triggers"),
        "results": get(api, f"/projects/{project_id}/repositories/results"),
        "dataset": get(api, f"/projects/{project_id}/datasets"),
        "secret": get(api, f"/projects/{project_id}/secrets"),
    }


def resource_key(kind: str, resource: dict):
    """What the routes address a project resource by: the global resource's id, a secret's label."""
    return {
        "trigger": lambda: resource["trigger_repository"]["id"],
        "results": lambda: resource["results_repository"]["id"],
        "dataset": lambda: resource["dataset"]["id"],
        "secret": lambda: resource["secret"]["label"],
    }[kind]()


def resource_path(kind: str, project_id: int, key) -> str:
    return {
        "trigger": f"/projects/{project_id}/repositories/triggers/{key}",
        "results": f"/projects/{project_id}/repositories/results/{key}",
        "dataset": f"/projects/{project_id}/datasets/{key}",
        "secret": f"/projects/{project_id}/secrets/{key}",
    }[kind]


def global_path(kind: str, key) -> str:
    return {
        "trigger": f"/global/repositories/triggers/{key}",
        "results": f"/global/repositories/results/{key}",
        "dataset": f"/global/datasets/{key}",
        "secret": f"/global/secrets/{key}",
    }[kind]


def first_resource(api: FncliBackendAPI, project_id: int, kind: str) -> dict:
    found = project_resources(api, project_id)[kind]
    if not found:
        raise click.ClickException(f"The project has no {kind} resource")
    return found[0]


def report(response, expect: int | None) -> int:
    """Print a write's outcome. 0 when it is what was wanted: the `expect` status, or any success without one."""
    click.echo(f"HTTP {response.status_code}")
    click.echo(json.dumps(body_of(response), indent=2))
    if expect is None:
        return 0 if response.status_code < 400 else 1
    ok = response.status_code == expect
    click.echo(f"OK (expected {expect})" if ok else f"FAIL: expected {expect}, got {response.status_code}")
    return 0 if ok else 1


def snapshot(api: FncliBackendAPI, name: str) -> dict:
    """Everything about the project the QA plan asserts on: its resources, their pull requests, tasks and results."""
    project = find_project(api, name)
    pid = project.id
    found = project_resources(api, pid)
    trigger_resources = []
    for resource in found["trigger"]:
        repo_id = resource["trigger_repository"]["id"]
        prs = get(api, f"/projects/{pid}/repositories/triggers/{repo_id}/pull_requests", per_page=100)
        # Stored once per repository, so also for a resource that gets no trigger (project revoked or disabled)
        stored = get(api, f"/global/repositories/triggers/{repo_id}/pull_requests", per_page=1)
        trigger_resources.append(
            {
                "repository": resource["trigger_repository"].get("uri"),
                "repository_id": repo_id,
                "enabled": resource["enabled"], "revoked": resource["revoked"], "active": resource["active"],
                "global_enabled": resource["trigger_repository"].get("enabled"),
                "pr_count": resource.get("pr_count"),
                "stored_pr_count": stored["total"],
                "pull_requests": [
                    {k: pr.get(k) for k in ("number", "state", "state_cause", "task_id")} for pr in prs["items"]
                ],
            }
        )
    return {
        "project": get(api, f"/projects/{pid}"),
        "trigger_resources": trigger_resources,
        "results_resources": [
            {"repository": resource["results_repository"].get("uri"), "target_dir": resource["target_dir"],
             "enabled": resource["enabled"], "revoked": resource["revoked"], "active": resource["active"],
             "global_enabled": resource["results_repository"].get("enabled")}
            for resource in found["results"]
        ],
        "dataset_resources": [
            {"dataset": resource["dataset"].get("name"), "enabled": resource["enabled"], "revoked": resource["revoked"],
             "active": resource["active"]}
            for resource in found["dataset"]
        ],
        "secret_resources": [
            {"secret": resource["secret"].get("label"), "enabled": resource["enabled"], "revoked": resource["revoked"],
             "active": resource["active"]}
            for resource in found["secret"]
        ],
        "tasks": [
            {k: t.get(k) for k in ("id", "status", "name", "state_cause")}
            for t in get(api, f"/projects/{pid}/tasks", per_page=100)["tasks"]
        ],
        "results": [
            {k: r.get(k) for k in ("id", "task_id", "step", "state", "number", "url")}
            for r in get(api, f"/projects/{pid}/results")
        ],
    }


def set_project(
    api: FncliBackendAPI, name: str, enabled: str | None, backfill: bool, expect: int | None,
    revoked: str | None = None, admin_api: FncliBackendAPI | None = None,
) -> int:
    data = {}
    if enabled is not None:
        data["enabled"] = enabled == "true"
    if backfill:
        data["backfill"] = True
    if revoked is not None:
        data["revoked"] = revoked == "true"
    if not data:
        raise click.UsageError("Give --enabled, --revoked and/or --backfill")
    project = find_project(api, name)
    # Revoking is admin only, as for a project resource
    writer = admin_api if "revoked" in data else api
    return report(call(writer, "PATCH", f"/projects/{project.id}", json=data), expect)


def set_resource(
    api: FncliBackendAPI, name: str, kind: str, enabled: str | None, revoked: str | None, expect: int | None,
    target_dir: str | None = None, admin_api: FncliBackendAPI | None = None,
) -> int:
    data = {}
    if enabled is not None:
        data["enabled"] = enabled == "true"
    if revoked is not None:
        data["revoked"] = revoked == "true"
    if target_dir is not None:
        if kind != "results":
            raise click.UsageError("--target-dir is only for the results resource")
        data["target_dir"] = target_dir
    if not data:
        raise click.UsageError("Give --enabled, --revoked and/or --target-dir")
    project = find_project(api, name)
    key = resource_key(kind, first_resource(api, project.id, kind))
    # Revoking is admin only: the system user the rest of fncli logs in as is refused with a 403
    writer = admin_api if "revoked" in data else api
    return report(call(writer, "PATCH", resource_path(kind, project.id, key), json=data), expect)


def set_global(
    api: FncliBackendAPI, name: str, kind: str, enabled: str | None, expect: int | None,
    revoked: str | None = None, admin_api: FncliBackendAPI | None = None,
) -> int:
    """Turn the global resource behind the project's resource on or off, or revoke it from every project."""
    data = {}
    if enabled is not None:
        data["enabled"] = enabled == "true"
    if revoked is not None:
        if kind not in ("trigger", "results"):
            raise click.UsageError("--revoked is only for the trigger and results repositories")
        data["revoked"] = revoked == "true"
    if not data:
        raise click.UsageError("Give --enabled and/or --revoked")
    project = find_project(api, name)
    key = resource_key(kind, first_resource(api, project.id, kind))
    writer = admin_api if "revoked" in data else api
    return report(call(writer, "PATCH", global_path(kind, key), json=data), expect)


def set_secret(api: FncliBackendAPI, label: str, enabled: str, expect: int | None) -> int:
    """Turn a secret on or off. Off also disables every repository and dataset that uses it; on changes only the secret."""
    return report(call(api, "PATCH", f"/global/secrets/{label}", json={"enabled": enabled == "true"}), expect)


def setup_second_project(api: FncliBackendAPI, config: ProjectConfig, name: str) -> int:
    """A second project assigned the SAME global resources: created disabled, assigned, then enabled."""
    first = find_project(api, config.project_name)
    found = project_resources(api, first.id)
    created = call(api, "POST", "/projects", json={"name": name})
    if created.status_code >= 400:
        raise click.ClickException(f"Could not create project {name}: HTTP {created.status_code} {created.text[:200]}")
    pid = body_of(created)["id"]
    steps = [("PUT", resource_path("secret", pid, resource["secret"]["label"]), {}) for resource in found["secret"]]
    steps += [("PUT", resource_path("dataset", pid, resource["dataset"]["id"]), {}) for resource in found["dataset"]]
    steps += [
        ("PUT", resource_path("trigger", pid, resource["trigger_repository"]["id"]),
         {"watch_dir": resource["watch_dir"], "base_branch": resource["base_branch"]})
        for resource in found["trigger"]
    ]
    steps += [
        ("PUT", resource_path("results", pid, resource["results_repository"]["id"]), {"target_dir": resource["target_dir"]})
        for resource in found["results"]
    ]
    steps.append(("PATCH", f"/projects/{pid}", {"enabled": True}))
    for method, path, data in steps:
        response = call(api, method, path, json=data)
        click.echo(f"{method} {path} -> {response.status_code}")
        if response.status_code >= 400:
            raise click.ClickException(
                f"{response.text[:300]}\nProject {name} (id {pid}) is half set up: remove it with second-project-teardown"
            )
    click.echo(f"Second project {name} ready (id {pid}); inspect it with: fncli project-show --project {name}")
    return 0


def teardown_second_project(api: FncliBackendAPI, name: str, expect: int | None) -> int:
    project = find_project(api, name)
    return report(call(api, "DELETE", f"/projects/{project.id}"), expect)


def finish(code: int):
    if code:
        raise click.exceptions.Exit(code)


def project_option(command):
    return click.option("--project", default=None, help="Backend project name. Default: the test project.")(command)


def expect_option(command):
    return click.option("--expect", type=int, default=None, help="Assert this HTTP status (exit 1 if it differs).")(command)


@click.command("project-show")
@project_option
def project_show_command(project):
    """Print the project's resources, pull requests, tasks and results as JSON. Read-only."""
    logging.disable(logging.INFO)  # fncli logs to stdout: keep it clean so the output pipes into jq
    config = ProjectConfig()
    click.echo(json.dumps(snapshot(build_backend_api(config), project or config.project_name), indent=2))


@click.command("project-set")
@click.option("--enabled", type=BOOL, default=None)
@click.option("--revoked", type=BOOL, default=None, help="Admin only (logs in as the first Keycloak user). Takes effect immediately.")
@click.option(
    "--backfill", is_flag=True, default=False,
    help="With --enabled true on a disabled project: create the triggers of the pull requests stored while it was off, instead of skipping them.",
)
@project_option
@expect_option
def project_set_command(enabled, revoked, backfill, project, expect):
    """Enable or disable the project, or revoke or restore it. Enabling skips what was merged while it was off, unless --backfill."""
    config = ProjectConfig()
    admin_api = build_admin_backend_api(config) if revoked is not None else None
    finish(set_project(
        build_backend_api(config), project or config.project_name, enabled, backfill, expect, revoked, admin_api
    ))


@click.command("resource-set")
@click.argument("kind", type=click.Choice(KINDS))
@click.option("--enabled", type=BOOL, default=None)
@click.option("--revoked", type=BOOL, default=None, help="Admin only (logs in as the first Keycloak user). Takes effect immediately.")
@click.option("--target-dir", default=None, help="The results resource's target directory. Tasks created before the change then fail.")
@project_option
@expect_option
def resource_set_command(kind, enabled, revoked, target_dir, project, expect):
    """Set the enabled and/or revoked flag, or the target directory of a results resource, of the project's resource of that KIND."""
    config = ProjectConfig()
    admin_api = build_admin_backend_api(config) if revoked is not None else None
    finish(set_resource(
        build_backend_api(config), project or config.project_name, kind, enabled, revoked, expect, target_dir, admin_api
    ))


@click.command("global-set")
@click.argument("kind", type=click.Choice(KINDS))
@click.option("--enabled", type=BOOL, default=None)
@click.option(
    "--revoked", type=BOOL, default=None,
    help="Trigger and results only, from every project at once. Admin only (logs in as the first Keycloak user).",
)
@project_option
@expect_option
def global_set_command(kind, enabled, revoked, project, expect):
    """Turn the global resource behind the project's resource of that KIND on or off, or revoke or restore it."""
    config = ProjectConfig()
    admin_api = build_admin_backend_api(config) if revoked is not None else None
    finish(set_global(
        build_backend_api(config), project or config.project_name, kind, enabled, expect, revoked, admin_api
    ))


@click.command("secret-set")
@click.option(
    "--entity",
    type=click.Choice(list(SECRET_CONFIGS)),
    default="trigger",
    show_default=True,
    help="Whose secret: a repo's, or the dataset's.",
)
@click.option("--enabled", type=BOOL, required=True)
@expect_option
def secret_set_command(entity, enabled, expect):
    """Turn a secret on or off. Off also disables the repositories and datasets that use it, and they stay off when it is turned on."""
    config = SECRET_CONFIGS[entity]()
    finish(set_secret(build_backend_api(config), config.secret_label, enabled, expect))


@click.command("second-project-setup")
@click.argument("name")
def second_project_setup_command(name):
    """Create a second project assigned the SAME global resources as the test project, enabled."""
    config = ProjectConfig()
    finish(setup_second_project(build_backend_api(config), config, name))


@click.command("second-project-teardown")
@click.argument("name")
@expect_option
def second_project_teardown_command(name, expect):
    """Delete a project. The global resources it was assigned stay."""
    config = ProjectConfig()
    finish(teardown_second_project(build_backend_api(config), name, expect))


COMMANDS = [
    project_show_command,
    project_set_command,
    resource_set_command,
    global_set_command,
    secret_set_command,
    second_project_setup_command,
    second_project_teardown_command,
]
