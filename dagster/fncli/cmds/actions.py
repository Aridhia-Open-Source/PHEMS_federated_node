"""
`open-pr` opens a PR in the trigger repo, chained from the step commands in cmds/pr.py. The project's setup and
teardown are `fncli apply` and `fncli delete` (cmds/nodefile.py).
"""

import click

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


COMMANDS = [open_pr_command]
