"""
A PR in the Gitea trigger repo, through a task, to a merged results PR in the results repo.
One test per fncli command or state change, run in order on one project: a failure names the
hop, and the first failure stops the run.
"""

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.pr import (
    commit_gitea_file_command,
    create_gitea_branch_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
    merge_results_pr_command,
    new_branch_name,
)
from fncli.cmds.sensor import ALL_SENSORS
from fncli.tests.e2e.conftest import (
    PR_STATES,
    RESULT_STEPS,
    SETUP_IDS,
    TASK_STATUSES,
    TEARDOWN_IDS,
    pull_requests,
    reached,
    start_sensor,
    teardown_step,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_success]

TASK_TIMEOUT = 600
STEP_TIMEOUT = 300


@pytest.fixture(scope="module")
def flow():
    """What the steps hand on to each other."""
    return {}


def our_pr(snapshot, flow):
    return next((pr for pr in pull_requests(snapshot) if pr["number"] == flow["pr_number"]), None)


def our_task(snapshot, flow):
    return next((t for t in snapshot["tasks"] if t["id"] == flow["task_id"]), None)


def our_result(snapshot, flow):
    return next((r for r in snapshot["results"] if r["task_id"] == flow["task_id"]), None)


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_leftovers(fncli, command, options):
    fncli.call(command, **options)


@pytest.mark.parametrize("command, options", SETUP_STEPS, ids=SETUP_IDS)
def test_setup(fncli, command, options):
    fncli.call(command, **options)


def test_verify_project_after_setup(fncli):
    fncli.run("verify-project")


@pytest.mark.parametrize("sensor", ALL_SENSORS)
def test_start_sensor(sensor):
    start_sensor(sensor)


def test_create_gitea_branch(fncli, flow):
    flow["branch"] = new_branch_name()
    fncli.call(create_gitea_branch_command, branch=flow["branch"])


def test_commit_gitea_file(fncli, flow):
    fncli.call(commit_gitea_file_command, branch=flow["branch"], kind="watched")


def test_create_gitea_pr(fncli, flow):
    flow["pr_number"] = fncli.call(create_gitea_pr_command, branch=flow["branch"], kind="watched")["number"]


def test_merge_gitea_pr(fncli, flow):
    fncli.call(merge_gitea_pr_command, number=flow["pr_number"], watch=False, timeout=0)


def test_pr_ingested(fncli, flow):
    def ingested(snapshot):
        pr = our_pr(snapshot, flow)
        return pr and reached(PR_STATES, pr["state"], "UNKNOWN")

    fncli.wait_for_state(f"PR #{flow['pr_number']} ingested (UNKNOWN or later)", STEP_TIMEOUT, ingested)


def test_pr_yielded(fncli, flow):
    def yielded(snapshot):
        pr = our_pr(snapshot, flow)
        return pr if pr and pr["state"] == "YIELDED" and pr["task_id"] else None

    flow["task_id"] = fncli.wait_for_state(f"PR #{flow['pr_number']} YIELDED with a task_id", STEP_TIMEOUT, yielded)["task_id"]


def test_task_created(fncli, flow):
    fncli.wait_for_state(f"task {flow['task_id']} created", STEP_TIMEOUT, lambda s: our_task(s, flow))


@pytest.mark.parametrize(
    "status, timeout",
    [("QUEUED", STEP_TIMEOUT), ("RUNNING", STEP_TIMEOUT), ("SUCCESS", TASK_TIMEOUT)],
    ids=["queued", "started", "success"],
)
def test_task_status(fncli, flow, status, timeout):
    def check(snapshot):
        task = our_task(snapshot, flow)
        return task and reached(TASK_STATUSES, task["status"], status)

    fncli.wait_for_state(f"task {flow['task_id']} {status} (or later)", timeout, check)


def test_result_exists(fncli, flow):
    fncli.wait_for_state(f"a result of task {flow['task_id']}", STEP_TIMEOUT, lambda s: our_result(s, flow))


def test_result_pushed(fncli, flow):
    def check(snapshot):
        result = our_result(snapshot, flow)
        return result and reached(RESULT_STEPS, result["step"], "PUSHED")

    fncli.wait_for_state(f"the result of task {flow['task_id']} at step PUSHED (or later)", STEP_TIMEOUT, check)


def test_result_opened(fncli, flow):
    def check(snapshot):
        result = our_result(snapshot, flow)
        return result if result and reached(RESULT_STEPS, result["step"], "OPENED") else None

    flow["results_number"] = fncli.wait_for_state(f"the result of task {flow['task_id']} at step OPENED (or later)", STEP_TIMEOUT, check)["number"]


def test_merge_results_pr(fncli, flow):
    fncli.call(merge_results_pr_command, number=flow["results_number"])


def test_result_merged(fncli, flow):
    def check(snapshot):
        result = our_result(snapshot, flow)
        return result and reached(RESULT_STEPS, result["step"], "MERGED")

    fncli.wait_for_state(f"the result of task {flow['task_id']} at step MERGED", STEP_TIMEOUT, check)


def test_verify_project_at_end(fncli):
    fncli.run("verify-project")


def test_verify_repo(fncli):
    fncli.run("verify-repo", "--tail", "1")


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
