"""
Checks the backend state during scripts/e2e_shared_resources.sh. Run with the python of the pipx venv fncli is installed in
(the shell script does this), from the repo root, so fncli finds .dev.env.

    e2e_check.py snapshot                     print the test project's links, PRs and tasks as JSON
    e2e_check.py wait-prs [--timeout SECONDS] wait until the PRs the script opened are all evaluated, then check them
    e2e_check.py wait-tasks [--timeout SECONDS] wait until every task is finished (SUCCESS), warn if not

NOT RUN in the cloud session that wrote it: there is no cluster there. It only reads (GET) from the backend.
"""

import argparse
import json
import sys
import time

from fncli.cmds.common import ProjectConfig, build_backend_api

TERMINAL_TASK_STATUSES = {"SUCCESS", "FAILED", "CANCELED"}


def get_json(api, path, **params):
    return api.session.get(path, params=params).json()


def snapshot(api, project_name):
    project = api.find_project(project_name)
    if project is None:
        raise SystemExit(f"project {project_name!r} not found: did setup-project run?")
    links = get_json(api, f"/projects/{project.id}/repositories/triggers")
    out = {"project": {"id": project.id, "enabled": project.enabled}, "trigger_links": [], "tasks": []}
    for link in links:
        repo_id = link["trigger_repository"]["id"]
        prs = get_json(api, f"/projects/{project.id}/repositories/triggers/{repo_id}/pull_requests", per_page=100)
        out["trigger_links"].append(
            {
                "repository_id": repo_id,
                "active": link["active"],
                "pull_requests": [
                    {k: pr.get(k) for k in ("number", "state", "state_cause", "task_id")} for pr in prs["items"]
                ],
            }
        )
    out["tasks"] = [
        {k: task.get(k) for k in ("id", "status", "name")}
        for task in get_json(api, f"/projects/{project.id}/tasks", per_page=100)["tasks"]
    ]
    return out


def wait_for(check, timeout, interval=10):
    deadline = time.time() + timeout
    while True:
        result = check()
        if result is not None:
            return result
        remaining = deadline - time.time()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))


def command_snapshot(api, config, _args):
    print(json.dumps(snapshot(api, config.project_name), indent=2))
    return 0


def command_wait_prs(api, config, args):
    """The script opens a watched, an unwatched and an invalid PR: expect YIELDED (with a task) and REJECTED, and no trigger for the unwatched one."""
    want = {"YIELDED", "REJECTED"}

    def check():
        snap = snapshot(api, config.project_name)
        states = {pr["state"] for link in snap["trigger_links"] for pr in link["pull_requests"]}
        return snap if want <= states else None

    snap = wait_for(check, args.timeout)
    if snap is None:
        print("FAIL: timed out waiting for YIELDED and REJECTED pull requests. Last snapshot:")
        print(json.dumps(snapshot(api, config.project_name), indent=2))
        print("Check: fncli sensor-status (ingest and evaluate running? errors in the ticks?)")
        return 1
    prs = [pr for link in snap["trigger_links"] for pr in link["pull_requests"]]
    problems = []
    for link in snap["trigger_links"]:
        if len(link["pull_requests"]) != 2:
            problems.append(f"link {link.get('repository_id', '?')} has {len(link['pull_requests'])} pull requests, expected 2 (the watched and the invalid one: the unwatched PR creates no trigger)")
    for pr in prs:
        if pr["state"] == "YIELDED" and not pr["task_id"]:
            problems.append(f"PR {pr['number']} is YIELDED but has no task_id")
        if pr["state"] == "REJECTED" and not pr["state_cause"]:
            problems.append(f"PR {pr['number']} is {pr['state']} but has no state_cause")
    if not snap["tasks"]:
        problems.append("no tasks for the project")
    print(json.dumps(snap, indent=2))
    if problems:
        print("FAIL:\n  " + "\n  ".join(problems))
        return 1
    print("OK: PRs evaluated, tasks created")
    return 0


def command_wait_tasks(api, config, args):
    def check():
        tasks = snapshot(api, config.project_name)["tasks"]
        return tasks if tasks and all(t["status"] in TERMINAL_TASK_STATUSES for t in tasks) else None

    tasks = wait_for(check, args.timeout)
    if tasks is None:
        print("WARN: tasks not finished in time:")
        print(json.dumps(snapshot(api, config.project_name)["tasks"], indent=2))
        print("Check: fncli sensor-status (launcher and the five run-status sensors), and the Dagster UI runs.")
        return 1
    print(json.dumps(tasks, indent=2))
    failed = [t for t in tasks if t["status"] != "SUCCESS"]
    if failed:
        print(f"FAIL: {len(failed)} task(s) finished without SUCCESS")
        return 1
    print("OK: all tasks SUCCESS")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    for name, default in (("wait-prs", 300), ("wait-tasks", 600)):
        p = sub.add_parser(name)
        p.add_argument("--timeout", type=int, default=default)
    args = parser.parse_args()

    config = ProjectConfig()
    api = build_backend_api(config)
    handler = {"snapshot": command_snapshot, "wait-prs": command_wait_prs, "wait-tasks": command_wait_tasks}[
        args.command
    ]
    return handler(api, config, args)


if __name__ == "__main__":
    sys.exit(main())
