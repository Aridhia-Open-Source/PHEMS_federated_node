"""
Commands that open a pull request in the Gitea trigger repo for the sensor to find. Each
step is its own command; `open-pr` runs them in order. The branch name is the one handle
that ties the steps together: the file and the PR title are derived from it.
"""

import json
import logging
from datetime import datetime, timezone

import click
from pydantic import Field

from fncli.cmds.common import GiteaConfig, build_gitea_api
from fncli.cmds.repository import init_gitea_repo

logger = logging.getLogger("pr")

# What the sensor makes of the pull request: a task (watched), ignore it (unwatched, the
# file is outside the watch_dir) or reject it (invalid, the spec does not validate).
KINDS = ["watched", "unwatched", "invalid"]


class PrConfig(GiteaConfig):
    repo: str = Field(default="", alias="TEST_TRIGGER_REPO")
    watch_dir: str = Field(default="", alias="TEST_TRIGGER_REPO_WATCH_DIR")
    pr_image: str = Field(default="busybox:latest", alias="TEST_PR_IMAGE")

    @property
    def repo_path(self) -> str:
        return f"{self.gitea_admin_user}/{self.repo}"


branch_option = click.option(
    "--branch", required=True, help="The PR's branch, as printed by create-gitea-branch."
)


def new_branch_name() -> str:
    """Unique per run, so every command can be re-run."""
    return f"pr-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def file_for(config: PrConfig, branch: str, kind: str) -> tuple[str, str]:
    """The path and content of the one new file a PR of that kind carries."""
    if kind == "unwatched":
        return f"docs/{branch}.md", f"# {branch}\n\nNot a spec: outside the watch_dir.\n"
    spec = {"name": branch, "image": config.pr_image}
    if kind == "invalid":
        # PullRequestSpec forbids unknown fields
        spec["unknown_field"] = True
    return f"{config.watch_dir}{branch}.json", json.dumps({"spec": spec}, indent=2) + "\n"


@click.command("create-gitea-branch")
@click.option("--branch", default=None, help="Branch name. Default: unique, from the time.")
def create_gitea_branch_command(branch):
    """Create a branch off the trigger repo's default branch."""
    config = PrConfig()
    branch = branch or new_branch_name()
    gitea_api = build_gitea_api(config)
    gitea_repo = init_gitea_repo(config, gitea_api)
    gitea_api.create_branch(config.repo_path, branch, gitea_repo["default_branch"])
    logger.info(f"Created branch {branch}")


@click.command("commit-gitea-file")
@branch_option
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
def commit_gitea_file_command(branch, kind):
    """Commit one new file to the branch, of a kind that decides what the sensor does."""
    config = PrConfig()
    file_path, content = file_for(config, branch, kind)
    build_gitea_api(config).create_file(
        config.repo_path, file_path, content, message=f"Add {file_path}", branch=branch
    )
    logger.info(f"Committed {kind} file {file_path} to {branch}")


@click.command("create-gitea-pr")
@branch_option
@click.option("--kind", type=click.Choice(KINDS), default="watched", show_default=True)
def create_gitea_pr_command(branch, kind):
    """Open a PR from the branch into the trigger repo's default branch."""
    config = PrConfig()
    gitea_api = build_gitea_api(config)
    gitea_repo = init_gitea_repo(config, gitea_api)
    pr = gitea_api.create_pull_request(
        config.repo_path,
        head_branch=branch,
        base_branch=gitea_repo["default_branch"],
        title=f"{kind} {branch}",
        body=f"A {kind} pull request, opened by fncli",
    )
    logger.info(f"Opened PR #{pr['number']}: {pr['html_url']}")
    return pr


@click.command("merge-gitea-pr")
@click.option("--number", required=True, type=int, help="The PR's number.")
def merge_gitea_pr_command(number):
    """Merge a PR in the trigger repo, which is what makes the sensor pick it up."""
    config = PrConfig()
    build_gitea_api(config).merge_pull_request(config.repo_path, number)
    logger.info(f"Merged PR #{number}")


COMMANDS = [
    create_gitea_branch_command,
    commit_gitea_file_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
]
