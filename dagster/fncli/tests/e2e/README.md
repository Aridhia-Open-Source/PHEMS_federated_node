# End-to-end suites

The suites run the real stack (webserver, Keycloak, Postgres, Dagster and Gitea on the `kind-fn` cluster) through fncli. They check what the unit tests cannot: that the sensors, the webserver rules and Gitea work together. The Gitea mirror, authentication and normal-user permissions are not covered.

| Suite | File | What it covers |
|---|---|---|
| `success` | `test_happy_path.py` | A PR in the trigger repository, through ingest, a task and delivery, to a merged results PR; `verify-project` and `verify-repo` pass |
| `failure` | `test_failure_paths.py` | The quick failure paths, none of which waits for a task to run: invalid spec rejected, unwatched PR creates no trigger, revoked link; then revoked project, disabled link, disabled and revoked global resource, disabled secret (a PR merged while each is off gets no task, also after it is switched back on) |
| `failure_long` | `test_failure_paths_long.py` | The long-running failure paths, where a task runs to the end or a result is delivered: second project on the same repository, lost token and recovery, failing task, project enabled with backfill; then work in flight: results link switched off before delivery (held `FAILED`, delivered by the retry sensor once on) |

Each test is one fncli command or one expected state, in order, on one project. The first failure stops the run and prints the last project snapshot. The "nothing happens" checks wait five sensor ticks.

The failure paths are split by what a group waits for. `failure` holds the groups made of commands, a state to reach and "nothing happens" ticks: no task has to run, so it finishes first. `failure_long` holds the groups that wait for a task to run to the end or for its result to be delivered, so it takes much longer and comes last. Each of the two clears the project at the start, sets it up and (with `E2E_TEARDOWN=1`) tears it down at the end, so either runs on its own on a fresh project.

## Rules

- Run against the local `kind-fn` cluster only: never a shared or production cluster.
- Never tear the dev cluster down (`make teardown`) to run the suites. Use the cluster that is running (`kubectl` on context `kind-fn`, Tilt green). If there is none, create it with `make helm_deps && make deploy` and `tilt up --stream` ([EXAMPLES.md](../../EXAMPLES.md)).
- Work from the worktree that owns the cluster (`make deploy-owner` shows it) and do not switch branches in the main checkout.
- Only the test project, its global resources, its Gitea repositories and the `QaTwo` project are created or changed. `teardown-project` removes them.
- A failing test is a finding: the suites report, they do not fix. Record the scenario, the commands, the expected and the actual result, and the logs.

## Preflight

- `kubectl config current-context` is `kind-fn`.
- The backend (`:5000`), Gitea (`:4000`), Dagster (`:3000`) and Keycloak (`:8080`) answer on localhost (port-forwards or Tilt).
- `.dev.env` exists in the repo root and defines `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD` (the first Keycloak user, needed to revoke links) and the `TEST_*` values documented in `.dev.env.example`.
- The images in the cluster are built from the branch under test (`make deploy`), including `pypipes-fn`.
- `jq` is installed when you run the scenarios by hand.

## Run

From the repo root, where fncli finds `.dev.env`:

```bash
dagster/.venv/bin/python -m pytest dagster --e2e success -v -x -p no:cacheprovider
dagster/.venv/bin/python -m pytest dagster --e2e failure -v -x -p no:cacheprovider
dagster/.venv/bin/python -m pytest dagster --e2e failure_long -v -x -p no:cacheprovider
```

All sensors must already be running before a run (`fncli start-sensor --sensor all`); the suites do not start them. `--e2e` alone runs all three in that order: `success`, `failure`, then `failure_long`. The project is cleared at the start of each run and left in place afterwards for inspection; `E2E_TEARDOWN=1` tears it down at the end. `E2E_FAST_SENSORS=1` sets the sensor interval to 1 s for the run (it patches the Dagster config and restarts the code server, which stops the sensors, so start them again with `fncli start-sensor --sensor all` before the run). `E2E_TASK_TIMEOUT` (default 600 s) bounds a task that has to start. Wrap a run in `timeout 3600` if `pytest-timeout` is not installed.

The `failing task` scenario needs the run image to honour `PYPIPES_EXIT_CODE`, which the rebuilt `pypipes-fn` does.

## Removed for now

The scenarios that stop and start sensors were removed from the suites and will be looked at again later. The reconcile sensor is expected to make up for sensors being down. These behaviours are not checked end to end until they are added back (the rules are in [revoke-and-enabled.md](../../../../docs/architecture/revoke-and-enabled.md)):

- `failure` or `failure_long`: restarting the ingest sensor does not duplicate pull requests or tasks, also after a trigger link was revoked and un-revoked.
- `failure` or `failure_long`: a task whose results link's `target_dir` changes before it launches fails, and its cause names the change ("May a waiting task launch?": the pinned configuration changed).
- `failure` or `failure_long`: sensors that were all stopped while a pull request was merged catch up when started: the pull request gets one trigger and one task, and no task stays `PENDING`.
- `failure` or `failure_long`: a results link revoked after the task succeeded and before its delivery leaves the result `REVOKED` and `FAILED`, never delivered, and un-revoking the link delivers nothing ("May a finished task's result be delivered?").
- `failure` or `failure_long`: a results link's `target_dir` changed after the task succeeded and before its delivery leaves the result `STALE` and `FAILED`, never delivered, and restoring the `target_dir` delivers nothing.
- `failure` or `failure_long`: a dataset link revoked while the task is `PENDING` makes the task fail at launch with a cause that starts "revoked: " and names the dataset, with no result.
- `failure` or `failure_long`: a global dataset switched off while the task is `PENDING` makes the task fail at launch with a cause saying the dataset is not active and naming it, with no result.

## After a failure

Capture `fncli sensor-status` and the last 200 lines of the backend and the Dagster code server (`kubectl get pods -A | grep -E "backend|dagster"`, then `kubectl logs <pod> --tail=200`). `fncli project-show` prints the project's links, pull requests, tasks and results as JSON.

## Probes outside the suites

These are worth a manual check, not a pass or fail:

- More than 100 merged PRs behind one cursor: stop ingest, merge 101 watched PRs, start ingest. Ingest posts them in batches of 100, so all are stored.
- A revoked secret link: `fncli link-set secret --revoked true`, then open a PR. Revoked secret links are not checked when a token is read.
