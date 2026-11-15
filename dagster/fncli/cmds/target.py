"""
The node a command works on: the context option (bootstrap/context.yaml, or --context FILE), the project of a step
command, and a backend client for the node. Every command that talks to the node first checks that kubectl points at
the node's cluster, because fncli reads the cluster's secrets from whatever context is current.
"""

import logging
from contextlib import contextmanager
from pathlib import Path

import click
from dotenv import load_dotenv

from fncli.backend import FncliBackendAPI
from fncli.cmds.common import BackendConfig, build_backend_api, find_under
from fncli.context import Context, load_context
from fncli.k8s import current_context


@contextmanager
def quiet_backend_logs():
    """The backend and Gitea clients log every call at INFO, which would bury a command's own lines"""
    loggers = [logging.getLogger(name) for name in ("app", "fncli", "nexus_client")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels):
            logger.setLevel(level)


def resolve_context(ctx, param, value: Path) -> Context:
    return load_context(find_under(
        "bootstrap", value,
        ". Make your own: cp bootstrap/examples/context.yaml bootstrap/context.yaml (edit it), or give --context FILE",
    ))


def context_option(command):
    return click.option(
        "--context", "context", envvar="FNCLI_CONTEXT", default="context.yaml", show_default=True,
        type=click.Path(dir_okay=False, path_type=Path), callback=resolve_context,
        help="The context file (FNCLI_CONTEXT): the node's url, kubectl context and env file, and the defaults. "
        "A path, or one relative to the repo's bootstrap/, found from here up.",
    )(command)


def step_project_option(command):
    return click.option(
        "--project", default=None, help="The project to work on. Default: the context's defaults.project.",
    )(command)


def check_kube_context(context: Context):
    """Refuse unless kubectl points at the node's cluster, and load the node's env file"""
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


def open_target(context: Context, err: bool = False) -> FncliBackendAPI:
    """
    A backend client for the context's node, after check_kube_context. Says which node it is first (on stderr with
    err, for a command whose output is piped).
    """
    check_kube_context(context)
    node = context.node
    click.echo(f"Node {node.url}, kubectl context {node.kube_context}\n", err=err)
    return build_backend_api(BackendConfig(node=node))


def announce_defaults(context: Context, used: list[str], err: bool = False):
    """The first line of a command that took something from the defaults, so the wrong project is never used silently"""
    if used:
        click.echo(f"Using the defaults of {context.path}: {', '.join(used)}", err=err)


def step_target(context: Context, project: str | None, err: bool = False) -> tuple[str, FncliBackendAPI]:
    """
    What a step command (verify-project, project-set, open-pr, ...) works on: the project, from --project else the
    context's defaults.project (the first line says so), and a backend client for the context's node (open_target).
    Everything else it needs, the project's repositories and datasets, it reads from the node. With err the lines it
    prints go to stderr, for a command whose output is piped.
    """
    if project is None:
        project = context.defaults.project
        if project is None:
            raise click.UsageError(f"Give --project, or set defaults.project in {context.path}")
        announce_defaults(context, [f"project {project}"], err)
    return project, open_target(context, err)
