"""
The logic of the multi-provider simulation (`fncli simulate`), with no I/O so it can be tested on its own.

A layout of several projects over several git providers, trigger repositories and results repositories; a seeded plan
of pull requests to merge in each trigger repository; and a checker that compares the backend's end state with what that
plan must have produced, per project and repository. It looks for wrong-resource and concurrency mistakes: a pull request
that reaches a project not assigned its repository, a task shared by two projects, results delivered to another
project's results repository, a number from one repository mistaken for the same number in another.
"""

import random
from dataclasses import dataclass

# What a pull request of each kind must lead to, see fncli.cmds.pr.KINDS
WATCHED, UNWATCHED, INVALID, FAILING = "watched", "unwatched", "invalid", "failing"
KIND_WEIGHTS = [(WATCHED, 6), (INVALID, 1), (UNWATCHED, 1), (FAILING, 1)]
TERMINAL_TASK = {"SUCCESS", "FAILED", "CANCELED"}
DELIVERED_STEPS = {"OPENED", "MERGED"}


@dataclass(frozen=True)
class Layout:
    """Which provider each repository is on, and what each project is assigned."""

    trigger_repos: dict[str, str]  # repository name -> provider key
    results_repos: dict[str, str]
    projects: dict[str, dict]  # project name -> {"triggers": [repository names], "results": repository name}


# Provider "a" is the cluster's Gitea under its own name, "b" the same Gitea under an alias host. A repository is on
# one provider; one project watches two repositories on both providers, one repository is shared by two projects,
# and the projects deliver to different results repositories.
DEFAULT_LAYOUT = Layout(
    trigger_repos={"sim-trig-a1": "a", "sim-trig-a2": "a", "sim-trig-b1": "b"},
    results_repos={"sim-res-a": "a", "sim-res-b": "b"},
    projects={
        "SimOne": {"triggers": ["sim-trig-a1"], "results": "sim-res-a"},
        "SimTwo": {"triggers": ["sim-trig-a1", "sim-trig-b1"], "results": "sim-res-b"},
        "SimThree": {"triggers": ["sim-trig-a2"], "results": "sim-res-a"},
        "SimFour": {"triggers": ["sim-trig-b1"], "results": "sim-res-b"},
    },
)


def make_plan(layout: Layout, seed: int, per_repo: int) -> dict[str, list[str]]:
    """The kinds of the pull requests to merge in each trigger repository, in order. The first is always watched."""
    rng = random.Random(seed)
    kinds, weights = zip(*KIND_WEIGHTS)
    return {
        repo: [WATCHED] + rng.choices(kinds, weights=weights, k=per_repo - 1)
        for repo in sorted(layout.trigger_repos)
    }


def repo_of_resource(resource: dict) -> str:
    """The repository name of a trigger resource of a project snapshot: the last segment of its uri."""
    return (resource.get("repository") or "").rstrip("/").split("/")[-1]


def results_title(admin: str, repo: str, number: int, task_id: int) -> str:
    """The title delivery gives a results pull request, see ResultsDelivery."""
    return f"{admin}/{repo} PR{number} - task {task_id} - results"


def _yielded(kind: str) -> bool:
    return kind in (WATCHED, FAILING)


def _resources_of(snapshot: dict) -> dict[str, list[dict]]:
    return {repo_of_resource(resource): resource["pull_requests"] for resource in snapshot["trigger_resources"]}


def pending(layout: Layout, merged: dict[str, list[dict]], snapshots: dict[str, dict]) -> list[str]:
    """What the sensors have not done yet. Empty when every merged pull request is evaluated and every task settled."""
    waiting = []
    for project, spec in layout.projects.items():
        snapshot = snapshots[project]
        resources = _resources_of(snapshot)
        tasks = {task["id"]: task for task in snapshot["tasks"]}
        results = {result["task_id"]: result for result in snapshot["results"]}
        for repo in spec["triggers"]:
            seen = {pr["number"]: pr for pr in resources.get(repo, [])}
            for pull in merged.get(repo, []):
                if pull["kind"] == UNWATCHED:
                    continue
                pr = seen.get(pull["number"])
                label = f"{project}/{repo}#{pull['number']}"
                if pr is None or pr["state"] == "UNKNOWN":
                    waiting.append(f"{label} not evaluated")
                elif _yielded(pull["kind"]):
                    task = tasks.get(pr["task_id"])
                    if task is None or task["status"] not in TERMINAL_TASK:
                        waiting.append(f"{label} task {pr['task_id']} not finished")
                    elif pull["kind"] == WATCHED and task["status"] == "SUCCESS":
                        result = results.get(task["id"])
                        if result is None or result["step"] not in DELIVERED_STEPS:
                            waiting.append(f"{label} task {task['id']} not delivered")
    return waiting


def check(
    layout: Layout,
    merged: dict[str, list[dict]],
    snapshots: dict[str, dict],
    results_titles: dict[str, list[str]],
    admin: str,
) -> list[str]:
    """
    The problems found in the end state, empty when it is as the plan requires. `merged` is, per trigger repository,
    the pull requests that were merged: {"number", "kind"}. `snapshots` is the project snapshot of each project, and
    `results_titles` the titles of the pull requests of each results repository.
    """
    problems = []
    task_owner: dict[int, str] = {}
    expected_titles: dict[str, list[str]] = {name: [] for name in layout.results_repos}

    for project, spec in layout.projects.items():
        snapshot = snapshots[project]
        resources = _resources_of(snapshot)
        tasks = {task["id"]: task for task in snapshot["tasks"]}
        results = {result["task_id"]: result for result in snapshot["results"]}

        if set(resources) != set(spec["triggers"]):
            problems.append(f"{project}: assigned repositories {sorted(resources)}, expected {sorted(spec['triggers'])}")

        expected_tasks = 0
        for repo in spec["triggers"]:
            seen = {pr["number"]: pr for pr in resources.get(repo, [])}
            wanted = {pull["number"]: pull for pull in merged.get(repo, []) if pull["kind"] != UNWATCHED}
            for number in sorted(set(seen) - set(wanted)):
                problems.append(f"{project}/{repo}: unexpected pull request #{number} ({seen[number]['state']})")
            for number, pull in sorted(wanted.items()):
                label = f"{project}/{repo}#{number}"
                pr = seen.get(number)
                if pr is None:
                    problems.append(f"{label}: missing ({pull['kind']})")
                    continue
                if not _yielded(pull["kind"]):
                    if pr["state"] != "REJECTED" or pr["task_id"] is not None:
                        problems.append(f"{label}: {pull['kind']} should be REJECTED without a task, is {pr['state']} task {pr['task_id']}")
                    continue
                if pr["state"] != "YIELDED" or pr["task_id"] is None:
                    problems.append(f"{label}: {pull['kind']} should be YIELDED with a task, is {pr['state']} task {pr['task_id']}")
                    continue
                expected_tasks += 1
                task_id = pr["task_id"]
                if task_id in task_owner:
                    problems.append(f"{label}: task {task_id} is shared with {task_owner[task_id]}")
                task_owner[task_id] = label
                task = tasks.get(task_id)
                if task is None:
                    problems.append(f"{label}: task {task_id} is not one of the project's tasks")
                    continue
                want_status = "SUCCESS" if pull["kind"] == WATCHED else "FAILED"
                if task["status"] != want_status:
                    problems.append(f"{label}: task {task_id} is {task['status']}, expected {want_status}")
                result = results.get(task_id)
                if pull["kind"] == FAILING:
                    if result is not None:
                        problems.append(f"{label}: failed task {task_id} has a result ({result['step']})")
                elif result is None or result["step"] not in DELIVERED_STEPS:
                    problems.append(f"{label}: task {task_id} result is {result and result['step']}, expected OPENED or MERGED")
                else:
                    expected_titles[spec["results"]].append(results_title(admin, repo, number, task_id))

        if len(tasks) != expected_tasks:
            problems.append(f"{project}: {len(tasks)} tasks, expected {expected_tasks}")

    # Each results pull request is in its own project's results repository and in no other
    for repo, titles in results_titles.items():
        for title in titles:
            if title not in expected_titles.get(repo, []):
                problems.append(f"results repository {repo}: unexpected pull request {title!r}")
    for repo, titles in expected_titles.items():
        for title in titles:
            count = results_titles.get(repo, []).count(title)
            if count != 1:
                problems.append(f"results repository {repo}: {count} pull requests titled {title!r}, expected 1")
    return problems
