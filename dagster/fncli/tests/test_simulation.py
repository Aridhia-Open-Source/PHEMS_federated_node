"""The simulation's plan and checker (fncli.simulation) on built states, with no cluster."""

import copy

from fncli import simulation as sim

ADMIN = "gitea_admin"
LAYOUT = sim.DEFAULT_LAYOUT
# Pull requests merged in each trigger repository: the same numbers in different repositories on purpose
MERGED = {
    "sim-trig-a1": [{"number": 1, "kind": "watched"}, {"number": 2, "kind": "unwatched"}, {"number": 3, "kind": "invalid"}],
    "sim-trig-a2": [{"number": 1, "kind": "watched"}, {"number": 2, "kind": "failing"}],
    "sim-trig-b1": [{"number": 1, "kind": "watched"}, {"number": 2, "kind": "watched"}],
}


def ideal_state():
    """The snapshots of every project, and the results repositories' titles, as a correct run leaves them."""
    next_task = iter(range(100, 1000))
    snapshots, titles = {}, {name: [] for name in LAYOUT.results_repos}
    for project, spec in LAYOUT.projects.items():
        links, tasks, results = [], [], []
        for repo in spec["triggers"]:
            prs = []
            for pull in MERGED[repo]:
                if pull["kind"] == sim.UNWATCHED:
                    continue
                if pull["kind"] == sim.INVALID:
                    prs.append({"number": pull["number"], "state": "REJECTED", "state_cause": "x", "task_id": None})
                    continue
                task_id = next(next_task)
                prs.append({"number": pull["number"], "state": "YIELDED", "state_cause": None, "task_id": task_id})
                failing = pull["kind"] == sim.FAILING
                tasks.append({"id": task_id, "status": "FAILED" if failing else "SUCCESS", "name": "t"})
                if not failing:
                    results.append({"task_id": task_id, "step": "OPENED", "state": "DELIVERED"})
                    titles[spec["results"]].append(sim.results_title(ADMIN, repo, pull["number"], task_id))
            links.append({"repository": f"http://gitea.fn.svc:4000/{ADMIN}/{repo}", "pull_requests": prs})
        snapshots[project] = {"trigger_links": links, "tasks": tasks, "results": results}
    return snapshots, titles


def problems_of(snapshots, titles):
    return sim.check(LAYOUT, MERGED, snapshots, titles, ADMIN)


def test_the_plan_is_deterministic_and_starts_with_a_watched_pull_request():
    first = sim.make_plan(LAYOUT, seed=3, per_repo=5)
    assert first == sim.make_plan(LAYOUT, seed=3, per_repo=5)
    assert set(first) == set(LAYOUT.trigger_repos)
    assert all(len(kinds) == 5 and kinds[0] == sim.WATCHED for kinds in first.values())


def test_a_correct_end_state_has_no_problems_and_nothing_pending():
    snapshots, titles = ideal_state()
    assert problems_of(snapshots, titles) == []
    assert sim.pending(LAYOUT, MERGED, snapshots) == []


def test_an_unfinished_task_is_pending():
    snapshots, _ = ideal_state()
    snapshots["SimOne"]["tasks"][0]["status"] = "RUNNING"
    assert any("not finished" in item for item in sim.pending(LAYOUT, MERGED, snapshots))


def test_an_undelivered_result_is_pending():
    snapshots, _ = ideal_state()
    snapshots["SimOne"]["results"][0]["step"] = "PUSHED"
    assert any("not delivered" in item for item in sim.pending(LAYOUT, MERGED, snapshots))


def test_a_pull_request_that_reached_the_wrong_project_is_found():
    snapshots, titles = ideal_state()
    snapshots["SimThree"]["trigger_links"][0]["pull_requests"].append(
        {"number": 7, "state": "YIELDED", "state_cause": None, "task_id": 999}
    )
    assert any("SimThree/sim-trig-a2: unexpected pull request #7" in p for p in problems_of(snapshots, titles))


def test_a_task_shared_by_two_projects_is_found():
    snapshots, titles = ideal_state()
    shared = snapshots["SimOne"]["trigger_links"][0]["pull_requests"][0]["task_id"]
    snapshots["SimTwo"]["trigger_links"][0]["pull_requests"][0]["task_id"] = shared
    snapshots["SimTwo"]["tasks"][0]["id"] = shared
    assert any("is shared with" in p for p in problems_of(snapshots, titles))


def test_a_results_pull_request_in_the_wrong_repository_is_found():
    snapshots, titles = ideal_state()
    moved = titles["sim-res-a"].pop()
    titles["sim-res-b"].append(moved)
    problems = problems_of(snapshots, titles)
    assert any("results repository sim-res-b: unexpected" in p for p in problems)
    assert any("results repository sim-res-a: 0 pull requests" in p for p in problems)


def test_a_missing_pull_request_a_wrong_status_and_a_result_for_a_failed_task_are_found():
    snapshots, titles = ideal_state()
    del snapshots["SimFour"]["trigger_links"][0]["pull_requests"][1]
    snapshots["SimOne"]["tasks"][0]["status"] = "FAILED"
    failed_task = snapshots["SimThree"]["tasks"][1]["id"]
    snapshots["SimThree"]["results"].append({"task_id": failed_task, "step": "OPENED", "state": "DELIVERED"})
    problems = problems_of(snapshots, titles)
    assert any("SimFour/sim-trig-b1#2: missing" in p for p in problems)
    assert any("is FAILED, expected SUCCESS" in p for p in problems)
    assert any("failed task" in p and "has a result" in p for p in problems)


def test_a_rejected_pull_request_with_a_task_is_found():
    snapshots, titles = ideal_state()
    rejected = copy.deepcopy(snapshots)["SimOne"]["trigger_links"][0]["pull_requests"][1]
    assert rejected["state"] == "REJECTED"
    snapshots["SimOne"]["trigger_links"][0]["pull_requests"][1]["task_id"] = 5
    assert any("should be REJECTED without a task" in p for p in problems_of(snapshots, titles))


def test_a_project_linked_to_another_repository_is_found():
    snapshots, titles = ideal_state()
    snapshots["SimOne"]["trigger_links"].append(
        {"repository": f"http://gitea.fn.svc:4000/{ADMIN}/sim-trig-a2", "pull_requests": []}
    )
    assert any("SimOne: linked to repositories" in p for p in problems_of(snapshots, titles))
