# End-to-end suites

The suites run the real stack (webserver, Keycloak, Postgres, Dagster and Gitea on the `kind-fn` cluster) through fncli. They check what the unit tests cannot: that the sensors, the webserver rules and Gitea work together. The Gitea mirror, authentication and normal-user permissions are not covered.

| Suite | File | What it covers |
|---|---|---|
| `success` | `test_happy_path.py` | A PR in the trigger repository, through ingest, a task and delivery, to a merged results PR; `verify-project` and `verify-repo` pass |
| `failure` | `test_failure_paths.py` | Invalid spec rejected, unwatched PR creates no trigger, ingest restart is idempotent, revoked link, second project on the same repository, lost token and recovery, failing task, results `target_dir` change, sensors restarted mid-flow |
| `failure2` | `test_failure_paths_2.py` | Revoked project, disabled link, disabled and revoked global resource, disabled secret, backfill; then work in flight: results link revoked after the task launched (result `REVOKED`, still not delivered once un-revoked), results `target_dir` changed after launch (`STALE`), results link switched off before delivery (held `FAILED`, delivered by the retry sensor once on), dataset link revoked and global dataset switched off while the task is `PENDING` (fails at launch naming the dataset) |

Each test is one fncli command or one expected state, in order, on one project. The first failure stops the run and prints the last project snapshot. The "nothing happens" checks wait five sensor ticks.

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
dagster/.venv/bin/python -m pytest dagster --e2e failure2 -v -x -p no:cacheprovider
```

`--e2e` alone runs all three in that order. The project is cleared at the start of each run and left in place afterwards for inspection; `E2E_TEARDOWN=1` tears it down at the end. `E2E_FAST_SENSORS=1` sets the sensor interval to 1 s for the run (it patches the Dagster config and restarts the code server, so the sensors are started again by the suite). `E2E_TASK_TIMEOUT` (default 600 s) bounds a task that has to start. Wrap a run in `timeout 3600` if `pytest-timeout` is not installed.

The `failure2` work-in-flight scenarios stop and start the `delivery` and `launcher` sensors; they assume the delivery run-status sensor, once restarted, delivers a run that succeeded while it was stopped.

The `failing task` scenario needs the run image to honour `PYPIPES_EXIT_CODE`, which the rebuilt `pypipes-fn` does.

## After a failure

Capture `fncli sensor-status` and the last 200 lines of the backend and the Dagster code server (`kubectl get pods -A | grep -E "backend|dagster"`, then `kubectl logs <pod> --tail=200`). `fncli project-show` prints the project's links, pull requests, tasks and results as JSON.

## Probes outside the suites

These are worth a manual check, not a pass or fail:

- More than 100 merged PRs behind one cursor: stop ingest, merge 101 watched PRs, start ingest. Ingest posts them in batches of 100, so all are stored.
- A revoked secret link: `fncli link-set secret --revoked true`, then open a PR. Revoked secret links are not checked when a token is read.
