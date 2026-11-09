"""
Commands that work from a node file (fncli/DESIGN-node-file.md), named as kubectl's are. The node they work on is in
bootstrap/context.yaml (or --context FILE), not in the node file. `diff` is read-only: what applying the file would change. `apply` prints the same, asks, then carries it out in dependency order, stopping at the
first backend error. `delete` deletes what the file describes, in reverse order, skipping what the backend refuses. None
ever prints a secret value, only whether the source of each one is set or missing. All first check that kubectl points at
the cluster of the node, because fncli reads the cluster's secrets from whatever context is current.
"""

import logging
from collections.abc import Callable
from contextlib import contextmanager
from http import HTTPStatus
from pathlib import Path

import click
import requests
from dotenv import load_dotenv

from fncli.backend import FncliBackendAPI
from fncli.cmds.common import BackendConfig, GiteaConfig, build_backend_api, build_gitea_api, find_under
from fncli.k8s import current_context
from fncli.nodefile.apply import Applier, describe_error, missing_sources, needs_gitea, to_do, with_rotations
from fncli.nodefile.delete import DELETE, Remover, deletions, refusal
from fncli.nodefile.diff import BLOCKED, CONFIRM, CREATE, ENSURE, UNCHANGED, UPDATE, BackendState, Change, count, diff
from fncli.nodefile.loader import (
    Context, check_gitea_owners, check_sources, fail, limit_to_project, load_context, load_node_file,
)
from fncli.nodefile.schema import NodeFile
from fncli.nodefile.state import read_state

MARKS = {CREATE: "+", UPDATE: "~", UNCHANGED: "=", CONFIRM: "!", BLOCKED: "x", ENSURE: "?", DELETE: "-"}


@contextmanager
def quiet_backend_logs():
    """The backend and Gitea clients log every call at INFO, which would bury the plan and the lines of apply and delete"""
    loggers = [logging.getLogger(name) for name in ("app", "fncli")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels):
            logger.setLevel(level)


def render_change(change: Change, sources: dict) -> list[str]:
    """The plan's line for a change, and under it, for a secret to create, where each value is read from"""
    text = [change.detail, "; ".join(str(field) for field in change.fields)]
    line = f"  {MARKS[change.action]} {change.kind:<13} {change.name:<34} {'; '.join(part for part in text if part)}"
    if change.warnings:
        line += f"   ({', '.join(change.warnings)})"
    lines = [line.rstrip()]
    if change.also_used_by:
        lines.append(f"      also used by: {', '.join(change.also_used_by)}")
    if change.kind == "secret" and change.action in (CREATE, UPDATE):
        lines += [f"      {source.key}: {source.where}, {source.state}" for source in sources.get(change.name, [])]
    return lines


def render_summary(changes: list[Change]) -> str:
    counts = count(changes)
    parts = [
        f"{counts[CREATE]} to create" if counts[CREATE] else "",
        f"{counts[UPDATE]} to change" if counts[UPDATE] else "",
        f"{counts[CONFIRM]} needs a confirmation" if counts[CONFIRM] else "",
        f"{counts[BLOCKED]} blocked" if counts[BLOCKED] else "",
        f"{counts[ENSURE]} to check at apply" if counts[ENSURE] else "",
        f"{counts[UNCHANGED]} unchanged" if counts[UNCHANGED] else "",
    ]
    return f"Plan: {', '.join(part for part in parts if part) or 'nothing in the file'}. Nothing is deleted."


def render_plan(node: NodeFile, changes: list[Change]) -> str:
    """The plan as text. Secrets that would be written get their sources listed, as set or missing."""
    to_write = {change.name for change in changes if change.kind == "secret" and change.action in (CREATE, UPDATE)}
    sources = {label: check_sources(spec) for label, spec in node.secrets.items() if label in to_write}
    lines = [line for change in changes for line in render_change(change, sources)]
    return "\n".join(lines + ["", render_summary(changes)])


def resolve_node_file(ctx, param, value: Path) -> Path:
    return find_under("bootstrap", value)


def resolve_context(ctx, param, value: Path) -> Context:
    return load_context(find_under(
        "bootstrap", value,
        ". Make your own: cp bootstrap/examples/context.yaml bootstrap/context.yaml (edit it), or give --context FILE",
    ))


def node_file_option(command):
    return click.option(
        "-f", "--file", "node_file", envvar="FNCLI_NODE_FILE", required=True,
        type=click.Path(dir_okay=False, path_type=Path), callback=resolve_node_file,
        help="The node file (FNCLI_NODE_FILE): a path, or one relative to the repo's bootstrap/, e.g. "
        "examples/globals-github.yaml. It holds any of providers, secrets, repositories, datasets, projects; "
        "what it names and does not hold must be on the node.",
    )(command)


def context_option(command):
    return click.option(
        "--context", "context", envvar="FNCLI_CONTEXT", default="context.yaml", show_default=True,
        type=click.Path(dir_okay=False, path_type=Path), callback=resolve_context,
        help="The context file (FNCLI_CONTEXT): the node's url, kubectl context and env file, and the defaults. "
        "A path, or one relative to the repo's bootstrap/, found from here up.",
    )(command)


def project_option(command):
    return click.option(
        "--project", default=None, help="Only this project and the global resources it references.",
    )(command)


def open_target(context: Context) -> FncliBackendAPI:
    """
    A backend client for the context's node. Refuses unless kubectl points at the node's cluster, loads the node's env
    file, and says which node it is first.
    """
    node = context.node
    if current_context() != node.kube_context:
        raise click.ClickException(
            f"{context.path} is for kubectl context {node.kube_context}, but the current one is {current_context()}. "
            f"Switch with: kubectl config use-context {node.kube_context}"
        )
    if node.env_file:
        if not node.env_file.is_file():
            raise click.ClickException(f"node.env_file {node.env_file} not found from {context.path} up")
        load_dotenv(node.env_file, override=True)
    # By alias: given by field name next to the same variable in the env, pydantic rejects the field name as extra.
    config = BackendConfig(NEXUS_API_URL=node.url, KEYCLOAK_NAMESPACE=node.keycloak_namespace)
    click.echo(f"Node {node.url}, kubectl context {node.kube_context}\n")
    return build_backend_api(config)


def context_env(context: Context) -> dict[str, str]:
    """What the commands that read the env instead of the context (the step commands) need to reach the node"""
    return {
        "NEXUS_API_URL": context.node.url,
        "KEYCLOAK_NAMESPACE": context.node.keycloak_namespace,
        "GITEA_ADMIN_USER": context.node.gitea_admin_user,
    }


def announce_defaults(context: Context, used: list[str]):
    """The first line of a command that took something from the defaults, so the wrong project is never used silently"""
    if used:
        click.echo(f"Using the defaults of {context.path}: {', '.join(used)}")


def open_node(context: Context, node_file: Path, project: str | None) -> tuple[NodeFile, FncliBackendAPI]:
    """
    The node file, limited to the project if one is given, and a backend client for the context's node (open_target).
    The file's Gitea repositories must be the node's Gitea admin user's.
    """
    api = open_target(context)
    node = load_node_file(node_file)
    problems = check_gitea_owners(node, context.node.gitea_admin_user)
    if problems:
        fail(node_file, problems)
    if project:
        node = limit_to_project(node, project)
    return node, api


def read_plan(
    context: Context, node_file: Path, project: str | None
) -> tuple[NodeFile, FncliBackendAPI, BackendState, list[Change]]:
    """The node file, the backend client and state it was compared with, and what applying the file would change"""
    node, api = open_node(context, node_file, project)
    with quiet_backend_logs():
        state = read_state(api)
    return node, api, state, diff(node, state)


@click.command("diff")
@node_file_option
@context_option
@project_option
def diff_command(node_file, context, project):
    """Show what applying a node file would change on the node. Read-only, and it never prints a secret value."""
    node, _, _, changes = read_plan(context, node_file, project)
    click.echo(render_plan(node, changes))


# What `diff` was called before it took kubectl's name
plan_command = click.Command(
    "plan", callback=diff_command.callback, params=diff_command.params, help=diff_command.help, hidden=True
)


def label(change: Change) -> str:
    return f"{MARKS[change.action]} {change.kind} {change.name}"


def lines(changes: list[Change]) -> str:
    return "\n".join(f"  {label(change)}" for change in changes) or "  nothing"


def carry_out(
    todo: list[Change], run: Callable[[Change], None], skip_status: HTTPStatus | None = None
) -> list[tuple[Change, str]]:
    """
    Run the changes in order, a line each as it is done. The first failure stops everything, with what was done and
    what was not. A refusal with skip_status only skips that change, which is returned with the backend's reason.
    """
    skipped = []
    with quiet_backend_logs():
        for index, change in enumerate(todo):
            click.echo(f"  {label(change)} ... ", nl=False)
            try:
                run(change)
            except requests.HTTPError as error:
                if error.response.status_code != skip_status:
                    stop(error, todo, index, skipped)
                click.echo("skipped")
                skipped.append((change, refusal(error)))
                continue
            except Exception as error:
                stop(error, todo, index, skipped)
            click.echo("done")
    return skipped


def stop(error: Exception, todo: list[Change], index: int, skipped: list[tuple[Change, str]]):
    """Say what was done and what was not, and exit 1"""
    click.echo("failed")
    skipped_changes = [change for change, _ in skipped]
    done = [change for change in todo[:index] if change not in skipped_changes]
    report = f"\nStopped: {describe_error(error)}\n\nDone:\n{lines(done)}\n"
    if skipped:
        report += f"\nSkipped, the backend refused:\n{lines(skipped_changes)}\n"
    click.echo(f"{report}\nNot done (the first one failed):\n{lines(todo[index:])}")
    raise click.exceptions.Exit(1)


def report_blocked(blocked: list[Change]):
    """What apply left alone because the backend refuses it, with the manual steps. Exits 1 if there is any."""
    if not blocked:
        return
    click.echo("\nNot applied, it needs a manual step:")
    for change in blocked:
        click.echo(f"  {label(change)}: {change.detail}")
    raise click.exceptions.Exit(1)


def apply_node_file(context: Context, node_file: Path, project: str | None, yes: bool, rotate: tuple[str, ...] = ()):
    """What `fncli apply` does: print the diff, ask unless yes, carry it out, exit 1 if something is left for a person"""
    node, api, state, changes = read_plan(context, node_file, project)
    changes = with_rotations(node, changes, rotate)
    click.echo(render_plan(node, changes))
    missing = missing_sources(node, changes)
    if missing:
        raise click.ClickException(
            "Nothing was applied, these secret values cannot be read:\n" + "\n".join(f"  {line}" for line in missing)
        )
    blocked = [change for change in changes if change.action == BLOCKED]
    todo = to_do(changes)
    if not todo:
        click.echo("\nNothing to do.")
        report_blocked(blocked)
        return
    gitea = build_gitea_api(GiteaConfig(GITEA_ADMIN_USER=context.node.gitea_admin_user)) if needs_gitea(node, todo) else None
    # Ensuring Gitea repositories alone writes nothing to the node and is safe to repeat, so it does not ask
    if not yes and any(change.action != ENSURE for change in todo):
        live = [change.name for change in todo if change.action == CONFIRM]
        question = "Apply?" if not live else (
            f"Apply? That disables {', '.join(live)} to assign its results repository, then enables it again"
        )
        click.confirm(question, abort=True)
    click.echo()
    carry_out(todo, Applier(node, state, api, gitea).run)
    click.echo(f"\nApplied {len(todo)} change{'s' * (len(todo) != 1)}.")
    report_blocked(blocked)


@click.command("apply")
@node_file_option
@context_option
@project_option
@click.option("-y", "--yes", is_flag=True, help="Do not ask before applying.")
@click.option(
    "--rotate", multiple=True, metavar="LABEL",
    help="Also rewrite this secret, though it exists (repeatable), and for a Gitea OAuth one, authorise its app again. "
    "Otherwise a secret is only written when missing.",
)
def apply_command(node_file, context, project, yes, rotate):
    """
    Make the node match a node file: print the diff, ask, then carry it out in dependency order (secrets, providers,
    repositories, datasets, projects). It stops at the first backend error and says what was done and what was not. A
    results repository on a live project is assigned by disabling the project and enabling it again, which the question
    mentions. A change the backend refuses (a swapped results repository, another default dataset) is skipped with its
    manual steps, and apply exits 1. Nothing is deleted (see delete). Never prints a secret value.
    """
    apply_node_file(context, node_file, project, yes, rotate)


def delete_from_node(node: NodeFile, api: FncliBackendAPI, with_globals: bool, yes: bool):
    """What `fncli delete` does to an opened node: list what goes, ask unless yes, delete, exit 1 if the backend refused any"""
    with quiet_backend_logs():
        state = read_state(api)
    rows, absent = deletions(node, state, with_globals)
    for change in rows:
        click.echo("\n".join(render_change(change, {})))
    if absent:
        click.echo(f"  {absent} of the file's entries are not on the node")
    todo = [change for change in rows if change.action == DELETE]
    if not todo:
        click.echo("\nNothing to delete.")
        return
    if node.gitea:
        click.echo("\nGitea repositories and OAuth apps that fncli created are left in place.")
    if not yes:
        click.confirm("\nDelete?", abort=True)
    click.echo()
    skipped = carry_out(todo, Remover(api).run, skip_status=HTTPStatus.CONFLICT)
    click.echo(f"\nDeleted {len(todo) - len(skipped)} of {len(todo)}.")
    if skipped:
        click.echo("\nSkipped, the backend refused:")
        for change, reason in skipped:
            click.echo(f"  {label(change)}: {reason}")
        raise click.exceptions.Exit(1)


def delete_node_file(context: Context, node_file: Path, with_globals: bool, yes: bool):
    delete_from_node(*open_node(context, node_file, None), with_globals, yes)


@click.command("delete")
@node_file_option
@context_option
@click.option(
    "--all", "with_globals", is_flag=True,
    help="Also delete the global resources the file describes: repositories and datasets, then secrets and providers.",
)
@click.option("-y", "--yes", is_flag=True, help="Do not ask before deleting.")
def delete_command(node_file, context, with_globals, yes):
    """
    Delete the projects a node file describes from the node, with their assignments. With --all, also the global
    repositories and datasets it describes, then the secrets (with their stored values) and the providers. Only what
    the node has. Nothing is forced: what a project outside the file still uses, or is still enabled, is skipped with
    the backend's message, and delete exits 1. A provider that repositories outside the file are on is kept. Gitea
    repositories and OAuth apps that fncli created are left in place.
    """
    delete_node_file(context, node_file, with_globals, yes)


COMMANDS = [diff_command, plan_command, apply_command, delete_command]
