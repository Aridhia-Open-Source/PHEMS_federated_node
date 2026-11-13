"""
`fncli trigger` runs a trigger file (triggers/): the JSON that asks the node to run a task, `{"spec": {"image": ...}}`.
By pull request (--pr) it opens a PR that adds the file under the project's trigger repository, which is how the
sensor finds it; the repository, watch directory and base branch are the project's own backend record, not the env.
By API (--api, not built yet) the same file would be sent to the task API. Chained from the step commands in cmds/pr.py.
The project's setup and teardown are `fncli apply` and `fncli delete` (cmds/nodefile.py).
"""

from pathlib import Path

import click

from fncli.cmds.nodefile import announce_defaults, context_option, open_target
from fncli.cmds.pr import (
    commit_file,
    create_branch,
    create_pr,
    load_trigger,
    merge_pr,
    new_branch_name,
    resolve_trigger,
    timeout_option,
    watch_option,
)
from fncli.cmds.repository import load_repo_config
from fncli.backend import FncliBackendAPI
from fncli.nodefile.loader import Context


def trigger_pr(
    context: Context, backend_api: FncliBackendAPI, project: str, trigger_file: Path, merge: bool, watch: bool, timeout: int
):
    """
    A branch, the trigger file under the watch directory of the project's trigger repository, a PR, and with merge the
    merge. The repository is the project's record in the node, read with backend_api.
    """
    config = load_repo_config("trigger", context, project, backend_api)
    trigger = load_trigger(trigger_file)
    branch = new_branch_name()
    create_branch(config, branch)
    commit_file(config, branch, "watched", trigger)
    pull_request = create_pr(config, branch, "watched")
    if merge:
        merge_pr(config, pull_request["number"], watch, timeout)


@click.command("trigger")
@click.argument("trigger_file", metavar="FILE", type=click.Path(dir_okay=False, path_type=Path), callback=resolve_trigger)
@context_option
@click.option("--project", default=None, help="The project to trigger. Default: the context's defaults.project.")
@click.option("--pr", is_flag=True, help="Open a pull request that adds FILE under the project's trigger repository.")
@click.option("--api", is_flag=True, help="Send FILE to the task API. Not built yet.")
@click.option("--merge", is_flag=True, help="With --pr, also merge the pull request.")
@watch_option
@timeout_option
def trigger_command(trigger_file, context, project, pr, api, merge, watch, timeout):
    """
    Trigger a task in a project with a trigger file: a path, or one relative to triggers/ (found from here up), such
    as examples/demo.json. With --pr: a branch, the file under the watch directory of the project's trigger
    repository, a PR, and with --merge the merge, which is what makes the sensor pick it up. The repository comes from
    the project's record in the node (fncli apply made it). The project and the way (--pr or --api) default to the
    context's defaults (bootstrap/context.yaml; FNCLI_DEFAULT_PROJECT and FNCLI_DEFAULT_TRIGGER_TYPE win over them),
    and the first line says when a default is used.
    """
    if pr and api:
        raise click.UsageError("Give --pr or --api, not both")
    explicit_project = project is not None
    way = "pr" if pr else "api" if api else context.defaults.trigger_type
    project = project or context.defaults.project
    if project is None or way is None:
        raise click.UsageError("Give --project and --pr or --api, or set them in the defaults of the context file")
    announce_defaults(context, [
        *([f"project {project}"] if not explicit_project else []),
        *([f"via {way}"] if not (pr or api) else []),
    ])
    if way == "api":
        raise click.ClickException("--api is not built yet: the task API takes a different body than a trigger file")
    trigger_pr(context, open_target(context), project, trigger_file, merge, watch, timeout)


COMMANDS = [trigger_command]
