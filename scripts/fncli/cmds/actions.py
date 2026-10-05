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
    init_dataset_secret_command,
    init_git_secret_command,
    verify_git_secret_command,
)

logger = logging.getLogger("actions")


# Each step with the options it runs with.
SETUP_STEPS = [
    (init_backend_project_command, {}),
    (init_gitea_repo_command, {"role": "trigger"}),
    (init_gitea_repo_command, {"role": "results"}),
    (init_git_secret_command, {"role": "trigger"}),
    (init_git_secret_command, {"role": "results"}),
    (init_dataset_secret_command, {}),
    (init_backend_trigger_repo_command, {}),
    (init_backend_results_repo_command, {}),
    (init_backend_dataset_command, {}),
    (verify_git_secret_command, {"role": "trigger"}),
    (verify_git_secret_command, {"role": "results"}),
    (project_healthcheck_command, {}),
]


@click.command("setup-project")
@click.pass_context
def setup_project_command(ctx):
    """Set up a whole dev project: two Gitea repos, secrets, and the backend records."""
    for step, options in SETUP_STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


# Each step with the options it runs with. A secret goes after what uses it, a repo after its token.
TEARDOWN_STEPS = [
    (delete_backend_dataset_command, {}),
    (delete_backend_results_repo_command, {}),
    (delete_backend_trigger_repo_command, {}),
    (delete_secret_command, {"role": "trigger"}),
    (delete_secret_command, {"role": "results"}),
    (delete_secret_command, {"role": "dataset"}),
    (delete_backend_project_command, {}),
    (delete_gitea_token_command, {"role": "trigger"}),
    (delete_gitea_token_command, {"role": "results"}),
    (delete_gitea_repo_command, {"role": "trigger"}),
    (delete_gitea_repo_command, {"role": "results"}),
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


@click.command("open-pr")
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
@click.option("--merge", is_flag=True, help="Also merge the PR.")
@click.pass_context
def open_pr_command(ctx, kind, merge):
    """Open a PR in the trigger repo: branch, file, PR, and with --merge the merge."""
    branch = new_branch_name()
    ctx.invoke(create_gitea_branch_command, branch=branch)
    ctx.invoke(commit_gitea_file_command, branch=branch, kind=kind)
    pr = ctx.invoke(create_gitea_pr_command, branch=branch, kind=kind)
    if merge:
        ctx.invoke(merge_gitea_pr_command, number=pr["number"])


COMMANDS = [setup_project_command, open_pr_command, teardown_project_command]
