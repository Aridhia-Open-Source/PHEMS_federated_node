"""
Commands that combine several actions, each chained from the step commands in the entity
modules: `setup-project` builds the whole dev project, `open-pr` opens a PR in it and
`teardown-project` takes it all down again, side effects included.
"""

import logging

import click

from fncli.cmds.dataset import delete_backend_dataset_command, init_backend_dataset_command
from fncli.cmds.pr import (
    KINDS,
    commit_gitea_file_command,
    create_gitea_branch_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
    new_branch_name,
    timeout_option,
    watch_option,
)
from fncli.cmds.project import (
    delete_backend_project_command,
    init_backend_project_command,
    project_healthcheck_command,
)
from fncli.cmds.repository import (
    delete_backend_results_repo_command,
    delete_backend_trigger_repo_command,
    delete_gitea_repo_command,
    init_backend_results_repo_command,
    init_backend_trigger_repo_command,
    init_gitea_repo_command,
)
from fncli.cmds.secret import (
    delete_gitea_token_command,
    delete_secret_command,
    init_backend_secret_command,
    init_dataset_secret_command,
    init_git_secret_command,
    verify_git_secret_command,
)

logger = logging.getLogger("actions")


# Each step with the options it runs with.
SETUP_STEPS = [
    (init_backend_project_command, {}),
    (init_gitea_repo_command, {"entity": "trigger"}),
    (init_gitea_repo_command, {"entity": "results"}),
    (init_git_secret_command, {"entity": "trigger"}),
    (init_git_secret_command, {"entity": "results"}),
    (init_dataset_secret_command, {}),
    (init_backend_trigger_repo_command, {}),
    (init_backend_results_repo_command, {}),
    (init_backend_dataset_command, {}),
    (verify_git_secret_command, {"entity": "trigger"}),
    (verify_git_secret_command, {"entity": "results"}),
    (project_healthcheck_command, {}),
]


@click.command("setup-project")
@click.pass_context
def setup_project_command(ctx):
    """Set up a whole dev project: two Gitea repos, secrets, and the backend records."""
    for step, options in SETUP_STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


# Each step with the options it runs with. delete_backend_project_command deletes all project
# contents (tasks, datasets, repos, secrets) in the right order, so it runs first. Per-record
# deletes after it log 'already gone' and skip. Gitea token/repo deletes come last.
TEARDOWN_STEPS = [
    (delete_backend_project_command, {}),
    (delete_backend_dataset_command, {}),
    (delete_backend_results_repo_command, {}),
    (delete_backend_trigger_repo_command, {}),
    (delete_secret_command, {"entity": "trigger"}),
    (delete_secret_command, {"entity": "results"}),
    (delete_secret_command, {"entity": "dataset"}),
    (delete_gitea_token_command, {"entity": "trigger"}),
    (delete_gitea_token_command, {"entity": "results"}),
    (delete_gitea_repo_command, {"entity": "trigger"}),
    (delete_gitea_repo_command, {"entity": "results"}),
]


@click.command("teardown-project")
@click.confirmation_option(
    "-y",
    "--yes",
    prompt="Delete the project, its secrets and both Gitea repos with all their pull requests?",
)
@click.pass_context
def teardown_project_command(ctx):
    """Delete the whole dev project, including both Gitea repos."""
    for step, options in TEARDOWN_STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


# Backend only: no Gitea call, so the git secrets hold placeholders and the trigger repo
# watches "main" until setup-gitea issues the tokens.
BACKEND_SETUP_STEPS = [
    (init_backend_project_command, {}),
    (init_backend_secret_command, {"entity": "trigger"}),
    (init_backend_secret_command, {"entity": "results"}),
    (init_backend_secret_command, {"entity": "dataset"}),
    (init_backend_trigger_repo_command, {"base_branch": "main"}),
    (init_backend_results_repo_command, {}),
    (init_backend_dataset_command, {}),
]

BACKEND_TEARDOWN_STEPS = [
    (delete_backend_project_command, {}),
    (delete_backend_dataset_command, {}),
    (delete_backend_results_repo_command, {}),
    (delete_backend_trigger_repo_command, {}),
    (delete_secret_command, {"entity": "trigger"}),
    (delete_secret_command, {"entity": "results"}),
    (delete_secret_command, {"entity": "dataset"}),
]

# Gitea only: the repos are the ones the project's backend records name.
GITEA_SETUP_STEPS = [
    (init_gitea_repo_command, {"entity": "trigger"}),
    (init_gitea_repo_command, {"entity": "results"}),
    (init_git_secret_command, {"entity": "trigger"}),
    (init_git_secret_command, {"entity": "results"}),
    (verify_git_secret_command, {"entity": "trigger"}),
    (verify_git_secret_command, {"entity": "results"}),
]

GITEA_TEARDOWN_STEPS = [
    (delete_gitea_token_command, {"entity": "trigger"}),
    (delete_gitea_token_command, {"entity": "results"}),
    (delete_gitea_repo_command, {"entity": "trigger"}),
    (delete_gitea_repo_command, {"entity": "results"}),
]

project_option = click.option(
    "--project", default=None, help="Backend project name. Default: TEST_PROJECT_NAME."
)


def run_steps(ctx, steps, extra_options=None):
    for step, options in steps:
        step_options = {**options, **(extra_options or {})}
        logger.info(f"=== {step.name} {step_options or ''} ===")
        ctx.invoke(step, **step_options)


@click.command("setup-backend")
@click.pass_context
def setup_backend_command(ctx):
    """Set up a project in the backend only (no Gitea): project, placeholder secrets, records."""
    run_steps(ctx, BACKEND_SETUP_STEPS)


@click.command("teardown-backend")
@click.confirmation_option(
    "-y",
    "--yes",
    prompt="Delete the project and its secrets from the backend?",
)
@click.pass_context
def teardown_backend_command(ctx):
    """Delete a project and its secrets from the backend only, leaving Gitea alone."""
    run_steps(ctx, BACKEND_TEARDOWN_STEPS)


@click.command("setup-gitea")
@project_option
@click.pass_context
def setup_gitea_command(ctx, project):
    """Set up the Gitea side of a backend project: its repos and tokens, stored in its secrets."""
    run_steps(ctx, GITEA_SETUP_STEPS, {"from_backend": True, "project": project})


@click.command("teardown-gitea")
@click.confirmation_option(
    "-y",
    "--yes",
    prompt="Delete the Gitea tokens and the repos, with all their pull requests?",
)
@project_option
@click.pass_context
def teardown_gitea_command(ctx, project):
    """Delete the Gitea tokens and repos of a backend project, leaving the backend alone."""
    run_steps(ctx, GITEA_TEARDOWN_STEPS, {"from_backend": True, "project": project})


@click.command("open-pr")
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
@click.option("--merge", is_flag=True, help="Also merge the PR.")
@watch_option
@timeout_option
@click.pass_context
def open_pr_command(ctx, kind, merge, watch, timeout):
    """Open a PR in the trigger repo: branch, file, PR, and with --merge the merge."""
    branch = new_branch_name()
    ctx.invoke(create_gitea_branch_command, branch=branch)
    ctx.invoke(commit_gitea_file_command, branch=branch, kind=kind)
    pr = ctx.invoke(create_gitea_pr_command, branch=branch, kind=kind)
    if merge:
        ctx.invoke(merge_gitea_pr_command, number=pr["number"], watch=watch, timeout=timeout)


COMMANDS = [
    setup_project_command,
    open_pr_command,
    teardown_project_command,
    setup_backend_command,
    teardown_backend_command,
    setup_gitea_command,
    teardown_gitea_command,
]
