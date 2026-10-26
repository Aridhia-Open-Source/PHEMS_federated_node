# QA test plan for the beta

A plan for a person to run by hand against a deployed node. It starts where the automated tests stop: [../TESTING.md](../TESTING.md) says what the unit, integration and end-to-end tests cover and what they cannot show; this plan covers the rest, and repeats a few automated paths on a real node.

It is written against the code at commit `6c46e803` (branch `moonshot/shared-resources`). Where this plan and the node disagree, record it as a finding. The decisions in [../decisions/README.md](../decisions/README.md) win over any text here, and the known issues are in [known-issues.md](known-issues.md).

## How to use the plan

- Each section is one file. Each case has a descriptive title, numbered steps, the expected result, the rule it checks, a line **Automated by:**, and two checkboxes.
- **Rule** gives the rule in words and cites the decision record by its title (with a link) or a file in `docs/architecture/`.
- **Automated by** is one of three labels, followed by the file or end-to-end group and, in a few words, what the automated part misses:
  - **Automated:** a test already checks the rule at the level the case works at.
  - **Partly automated:** a test covers part of it (named), and the case adds what the test cannot show: a live cluster, real timing, a real git host, several projects.
  - **Manual only:** no test covers it. Cases that were removed from the end-to-end suites say so in the title.
- "The end-to-end failure suite" is written but has never run on a cluster ([TESTING.md](../TESTING.md#checks-that-have-never-run-on-a-cluster)). Do not read "Partly automated: end-to-end failure suite" as "proven".
- Where the sources do not say what should happen, the case says **check** or "the sources do not say", and asks you to write down what you saw.

## What to have ready

| Need | For |
|---|---|
| A deployed node, and `kubectl` on its cluster | Every section |
| The administrator login (the first Keycloak user) | Anything with `--revoked`, global writes, the API calls |
| The Dagster UI | Sensor status, runs, ticks, run keys |
| The git host's UI (Gitea on the dev cluster) | Results pull requests, manual commits, closing a pull request |
| `jq`, `curl` | The state and counts commands below |
| `fncli` on the dev cluster (installed with `pipx`, see [../../dagster/fncli/README.md](../../dagster/fncli/README.md)) | Setup, pull requests, switches, sensors |
| A task image that runs for a while, and one that writes more than 10 MiB | A few cases; they say when they need it |

Which environment the commands are for:

- The `fncli` commands are written for the dev cluster: context `kind-fn`, the Tilt port-forwards (backend `:5000`, Gitea `:4000`, Dagster `:3000`, Keycloak `:8080`), a `.dev.env` in the repo root and the project that `fncli setup-project` creates. On any other node, check that `fncli` can reach it; if it cannot, use the HTTP route the case names, with an administrator bearer token.
- `fncli setup-project`, `teardown-project` and the `init-` and `delete-` commands create and delete GlobalResources and git repositories. Use them on the test project only, never on a shared node.
- The end-to-end suites use Gitea only. GitHub is checked by one case in [pull request ingest and task creation](pull-requests-and-task-creation.md).

Rules for the notes you keep:

- Never write a token, password or Secret value in a note, a ticket or a log excerpt. Never decode a Secret: to see where one is, list names only (`kubectl get secret -A | grep <name>`). Do not open `.dev.env`.
- Undo every change you make (switches, `target_dir`, tokens) and let all tasks and results settle before the next case: no task `PENDING`, `QUEUED` or `RUNNING`, no result still being delivered.

## Shorthand used in the steps

**Sensor interval.** The configured minimum interval of every sensor (`DAGSTER_SENSORS_MIN_INTERVAL_SECONDS`; 30 seconds by default, shorter on the dev cluster; read the real value from the first case in [deploy and health checks](deploy-and-health.md)). "Wait five intervals" means five sensor intervals: the same wait the end-to-end suites use for "nothing happens".

**Counts.** The numbers a case compares before and after:

```bash
fncli project-show | jq -c '{prs: .trigger_resources[0].pr_count, stored: .trigger_resources[0].stored_pr_count, tasks: (.tasks | length), results: (.results | length)}'
```

`prs` are the pull requests that have a trigger in the project; `stored` is how many the repository has stored, with or without a trigger for this project.

**Keep the project small.** `fncli project-show` lists at most 100 pull requests (the newest) and 100 tasks (the oldest, by id), so `tasks` in both commands, and the lists in the state command, stop growing at 100 and every "up by one" check is then silently wrong. `prs` and `stored` are totals and stay right. Before the project nears 90 tasks, recreate it: `fncli teardown-project -y`, then `fncli setup-project` (test project only), and start `fncli start-sensor --group all` again if the sensors stopped.

**State.** The states a case watches:

```bash
fncli project-show | jq -c '{project: (.project | {enabled, revoked}), trigger: (.trigger_resources[0] | {enabled, revoked, active, global_enabled}), result: (.results_resources[0] | {target_dir, enabled, revoked, active}), prs: [.trigger_resources[0].pull_requests[] | {number, state, task_id}], tasks: [.tasks[] | {id, status, state_cause}], results: [.results[] | {task_id, step, state, number}]}'
```

Add `--project QaTwo` to look at the second project.

**Merge a watched pull request.** `fncli open-pr --kind watched --merge`. Other kinds: `unwatched`, `invalid`, `failing` (a valid spec whose task exits non-zero).

**Second project.** `fncli second-project-setup QaTwo` creates a project with the same Secrets, dataset and repositories assigned as the test project, with the same settings, and enables it. `fncli second-project-teardown QaTwo` deletes it and leaves the GlobalResources. Use `QaThree` for a third.

**Make a change while a task is still PENDING.** Used by [task pinning](task-pinning.md) and [enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md).

1. `fncli stop-sensor --group launcher`.
2. Merge a watched pull request. Repeat the state command until the task exists and is `PENDING` (ingest and evaluate are still running).
3. Make the change the case asks for.
4. `fncli start-sensor --group launcher` and watch the task.

This is sound because the launcher reads the pending tasks again every tick and the webserver decides at launch.

**Make a change while a task is RUNNING or before delivery.** Used by the same two sections.

- Preferred: poll the state command and make the change as soon as the task is `RUNNING`. The checks that decide a result run when the result is created, after the task has succeeded, so a change made while the task runs has the same effect as one made after `SUCCESS` and before delivery.
- If the run is too short: `fncli stop-sensor --group delivery` before merging, make the change after the task is `SUCCESS`, then `fncli start-sensor --group delivery`. Caution: the sensor that launches the first delivery sees runs that finish after it starts, and the retry sensor only handles results that already exist as `FAILED`. A task that succeeded while the delivery sensors were stopped may never get a result. If no result appears after you start them, record it as a finding (see the delivery case in [sensors, restarts and catch-up](sensors-restarts-and-catch-up.md)).

## How to record a result

Keep a copy of each section file (or tick in place) and put this header at the top of your results:

```
Date:
Node and release:
Backend, Dagster and run-image tags:
Sensor interval:
Notes on the setup:
```

- Tick **Pass** or **Fail**. Leave both unticked for a case you did not run, and say why in the notes.
- A failing case is a finding: this plan reports, it does not fix. Write the case title, the commands you ran, the expected and actual result, and the logs. Always capture `fncli sensor-status`, the output of `fncli project-show`, and the last 200 lines of the backend and the Dagster code server (`kubectl get pods -A | grep -E "backend|dagster"`, then `kubectl logs <pod> --tail=200`).
- For the cases that ask you to "check" or "record", write what you saw even when you tick Pass.

## Where to spend the time

Ranked by risk: how complex the rules are, and how little of them an automated test proves. If you have little time, do [deploy and health checks](deploy-and-health.md) and the first case of [run a task and deliver the result](run-a-task-and-deliver-the-result.md) to know the node works at all, then work down this table.

| Section | Risk | Why |
|---|---|---|
| [Sensors, restarts and catch-up](sensors-restarts-and-catch-up.md) | Highest | Every scenario was removed from the end-to-end suites; the unit tests mock Dagster. Manual only. The reconcile sensor has never run against a live Dagster, and a task that finishes while the delivery sensors are stopped may never be delivered |
| [Task pinning](task-pinning.md) | Highest | Two behaviours removed from the end-to-end suites; the rest never had one. Only unit-tested. A change while a task waits or runs fails it or stales its result |
| [Enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md) | Highest | Three behaviours removed from the end-to-end suites and the rest unit-only; many orderings (revoked beats changed beats switched off); held results; work in flight |
| [Failures mid-flow and limits](failures-mid-flow-and-limits.md) | Highest | Nothing automated beyond one lost token: services down mid-flow, token expiry and rotation, concurrent merges, the size limit, stuck runs. May expose stuck items |
| [Enabled and revoked: pull requests and triggers](enabled-and-revoked-ingest-side.md) | High | The most complex rules. The end-to-end failure suite covers the trigger side only, and has never run on a cluster; GitProvider flags, combinations and the edge of the skipped gap are unit-only |
| [Secrets and quarantine](secrets-and-quarantine.md) | High | The unit tests use an in-memory store; the real move of a value between namespaces is checked only here |
| [Task and result state machines](task-and-result-state-machines.md) | High | Forward-only rules are unit-tested, but the live sensors that write them, the retry limit and the reconcile sensor are not |
| [Two projects on the same GlobalResources](two-projects-on-the-same-globalresources.md) | High | Tests use at most two projects and one pull request at a time; shared edits reach every project |
| [Pull request ingest and task creation](pull-requests-and-task-creation.md) | Medium | The matching rules are unit-tested; no end-to-end test of base branch, file types, spec files, datasets or GitHub |
| [Failure paths](failure-paths.md) | Medium | Each is in the end-to-end failure suite, which is written but has never run on a cluster |
| [Run a task and deliver the result](run-a-task-and-deliver-the-result.md) | Medium | The end-to-end success suite passed on the dev cluster, on Gitea only, before the launch endpoint and the reconcile sensor landed, and has not run since; layout, close and delete are not checked live |
| [GlobalResources and project resources](globalresources-and-project-resources.md) | Lower | Well covered by the route tests |
| [Deploy and health checks](deploy-and-health.md) | Lower, but do it first | Unit tests mock reachability |
| [Sign-in and admin-only actions](sign-in-and-admin-actions.md) | Lower | Only the administrator and the System user matter for the beta |
| [Permissions and what is out of scope](permissions-and-out-of-scope.md) | Lower | Mostly a list of what not to test |
| [Known issues](known-issues.md) | Lower | Known; record what you see |

## Order to work in

This is the dependency order; use the table above to choose where to put your time.

1. [Deploy and health checks](deploy-and-health.md): the node is up and honest about it.
2. [Sign-in and admin-only actions](sign-in-and-admin-actions.md): the logins you need for the rest.
3. [GlobalResources and project resources](globalresources-and-project-resources.md): the setup everything else builds on.
4. [Secrets and quarantine](secrets-and-quarantine.md): the real store, before anything depends on it. The last two cases need a task, so do them after "Run a task and deliver the result".
5. [Pull request ingest and task creation](pull-requests-and-task-creation.md): the matching rules.
6. [Two projects on the same GlobalResources](two-projects-on-the-same-globalresources.md): the second project is used by many later cases.
7. [Run a task and deliver the result](run-a-task-and-deliver-the-result.md): the main path, which later sections assume works.
8. [Failure paths](failure-paths.md).
9. [Enabled and revoked: pull requests and triggers](enabled-and-revoked-ingest-side.md).
10. [Enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md).
11. [Task pinning](task-pinning.md).
12. [Task and result state machines](task-and-result-state-machines.md).
13. [Sensors, restarts and catch-up](sensors-restarts-and-catch-up.md) (manual only, important).
14. [Failures mid-flow and limits](failures-mid-flow-and-limits.md).
15. [Permissions and what is out of scope](permissions-and-out-of-scope.md) and [known issues](known-issues.md).

## Sources

The cases are based on the end-to-end suites ([../../dagster/fncli/tests/e2e/README.md](../../dagster/fncli/tests/e2e/README.md)), the unit tests ([../TESTING.md](../TESTING.md)), the decision records in [../decisions/](../decisions/) and the architecture notes in [../../docs/architecture/](../../docs/architecture/): [revoke-and-enabled.md](../../docs/architecture/revoke-and-enabled.md), [flows.md](../../docs/architecture/flows.md), [entities.md](../../docs/architecture/entities.md) and [sensors/](../../docs/architecture/sensors/README.md).
