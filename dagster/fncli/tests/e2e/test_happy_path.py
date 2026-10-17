"""
A PR in the Gitea trigger repo, through a task, to a merged results PR in the results repo.
The steps share one project and run in order.
"""

import json

import pytest

from fncli.cmds.pr import (
    commit_gitea_file_command,
    create_gitea_branch_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
    new_branch_name,
)
from fncli.tests.e2e.conftest import wait_for

pytestmark = pytest.mark.e2e

TASK_TIMEOUT = 600
STEP_TIMEOUT = 300


@pytest.fixture(scope="module")
def flow():
    """What the steps hand on to each other."""
    return {}


def wait_for_state(fncli, what: str, timeout: float, check):
    """Poll the project snapshot until check(snapshot) is truthy and return it. On timeout the failure carries the last snapshot of PRs, tasks and results."""
    last = {}

    def poll():
        last["snapshot"] = fncli.snapshot()
        return check(last["snapshot"])

    try:
        return wait_for(poll, timeout, what)
    except pytest.fail.Exception as failure:
        shown = {
            "prs": [pr for link in last["snapshot"]["trigger_links"] for pr in link["pull_requests"]],
            "tasks": last["snapshot"]["tasks"],
            "results": last["snapshot"]["results"],
        }
        pytest.fail(f"{failure.msg}\nLast snapshot: {json.dumps(shown, indent=2)}")


def test_open_and_merge_pr(fncli, flow):
    fncli.run("start-sensor", "--sensor", "all")
    # The steps open-pr runs, called directly to get the PR's number back
    branch = new_branch_name()
    fncli.call(create_gitea_branch_command, branch=branch)
    fncli.call(commit_gitea_file_command, branch=branch, kind="watched")
    flow["pr_number"] = fncli.call(create_gitea_pr_command, branch=branch, kind="watched")["number"]
    fncli.call(merge_gitea_pr_command, number=flow["pr_number"], watch=False, timeout=0)


def test_pr_yields_task(fncli, flow):
    def yielded(snapshot):
        prs = [pr for link in snapshot["trigger_links"] for pr in link["pull_requests"]]
        return next((pr for pr in prs if pr["number"] == flow["pr_number"] and pr["state"] == "YIELDED" and pr["task_id"]), None)

    flow["task_id"] = wait_for_state(fncli, f"PR #{flow['pr_number']} YIELDED with a task_id", STEP_TIMEOUT, yielded)["task_id"]


def test_task_succeeds(fncli, flow):
    def succeeded(snapshot):
        return any(t["id"] == flow["task_id"] and t["status"] == "SUCCESS" for t in snapshot["tasks"])

    wait_for_state(fncli, f"task {flow['task_id']} SUCCESS", TASK_TIMEOUT, succeeded)


def test_results_pr_opened(fncli, flow):
    def opened(snapshot):
        return next((r for r in snapshot["results"] if r["task_id"] == flow["task_id"] and r["step"] == "OPENED"), None)

    flow["results_number"] = wait_for_state(fncli, f"a result of task {flow['task_id']} at step OPENED", STEP_TIMEOUT, opened)["number"]


def test_results_pr_merged(fncli, flow):
    fncli.run("merge-results-pr", "--number", str(flow["results_number"]))

    def merged(snapshot):
        return any(r["task_id"] == flow["task_id"] and r["step"] == "MERGED" for r in snapshot["results"])

    wait_for_state(fncli, f"the result of task {flow['task_id']} at step MERGED", STEP_TIMEOUT, merged)


def test_verify(fncli):
    fncli.run("verify-project")
    fncli.run("verify-repo")
