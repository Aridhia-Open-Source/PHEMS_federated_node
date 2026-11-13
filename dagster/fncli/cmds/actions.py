"""
`open-pr` opens a PR of a given kind in the project's trigger repo, chained from the step commands in
cmds/pr.py: what the end-to-end suites use for the kinds the sensor must ignore or
reject. To trigger a project's task with a trigger file, use `fncli trigger` (cmds/trigger.py). The project's setup and
teardown are `fncli apply` and `fncli delete` (cmds/nodefile.py).
"""

import click

from fncli.cmds.nodefile import context_option, step_project_option
from fncli.cmds.pr import (
    KINDS,
    commit_file,
    create_branch,
    create_pr,
    load_trigger,
    merge_pr,
    new_branch_name,
    timeout_option,
    trigger_option,
    watch_option,
)
from fncli.cmds.repository import step_repo_config


@click.command("open-pr")
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
@click.option("--merge", is_flag=True, help="Also merge the PR.")
@trigger_option
@watch_option
@timeout_option
@context_option
@step_project_option
def open_pr_command(kind, merge, trigger_file, watch, timeout, context, project):
    """Open a PR in the project's trigger repo: branch, file, PR, and with --merge the merge."""
    config = step_repo_config("trigger", context, project)
    branch = new_branch_name()
    create_branch(config, branch)
    commit_file(config, branch, kind, load_trigger(trigger_file))
    pull_request = create_pr(config, branch, kind)
    if merge:
        merge_pr(config, pull_request["number"], watch, timeout)


COMMANDS = [open_pr_command]
