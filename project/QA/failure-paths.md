# Failure paths

What the node does when the input is bad, a token is lost or a task fails. Each case is in the end-to-end failure suite, but that suite is written and has never been run on a cluster ([HANDOVER.md], "Run on a full environment"), so run them here. The cases that switch something off or revoke it are in the two enabled and revoked sections.

Needs: the dev project with all sensors running, and a finished happy path ([run a task and deliver the result](run-a-task-and-deliver-the-result.md)). Wait for any earlier task to finish before taking counts, or it will show up as new. "Counts" and "wait five intervals" are defined in [the index](README.md).

## An invalid spec is rejected and creates no task

1. Note the counts. `fncli open-pr --kind invalid --merge`.
2. Watch the pull request in `fncli project-show`. Wait five intervals.
3. Merge a normal watched pull request.

- **Expected:** the pull request goes `UNKNOWN` then `REJECTED` with a `state_cause` that says what is wrong; its `task_id` is empty; the task count does not change. The pull request count goes up by one. The next watched pull request still gets its task.
- **Rule:** a bad spec rejects the trigger and keeps the raw spec; no task; `REJECTED` is final ([TaskSpec, and a Task derived from spec and trigger]; [State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "an invalid spec is rejected, no task" (`dagster/fncli/tests/e2e/test_failure_paths.py`, written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py` (`test_bad_spec_rejects_the_pr`). The suite does not try to move the trigger on afterwards.
- [ ] Pass
- [ ] Fail — notes:

## A pull request outside the watched directory creates no trigger

1. Note the counts and the stored count. `fncli open-pr --kind unwatched --merge`.
2. Wait five intervals. Note them again.

- **Expected:** the stored count is up by one; the project's pull request and task counts are unchanged. Nothing is rejected: there is simply no trigger.
- **Rule:** a link gets a trigger only for a new `.json` file under its `watch_dir`; otherwise none (the cause is only logged) ([Pull requests stored once per repository, fanned out to project links, with cursors]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR outside the watched directory creates no trigger" (written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py`. The suite checks the project's counts, not the stored count.
- [ ] Pass
- [ ] Fail — notes:

## A lost trigger-repository token fails clearly, and the missed pull request is processed on recovery

1. Wait for tasks to finish. Note the counts.
2. `fncli delete-gitea-token --entity trigger`.
3. `fncli open-pr --kind watched --merge`. Wait five intervals; note the counts.
4. `fncli sensor-status`, and the Dagster UI tick log of `git_pull_request_ingest_sensor`.
5. `fncli project-healthcheck`.
6. `fncli init-git-secret --entity trigger`, then `fncli verify-git-secret --entity trigger`.
7. Watch `fncli project-show`; then `fncli project-healthcheck` again.

- **Expected:** step 3: the counts do not change. Step 4: the ingest sensor's ticks fail, naming the repository with an authentication error, while the evaluate and launcher sensors keep ticking. Step 5: exit code is not 0. Step 7: the pull request merged during the outage gets a trigger and a task (this is not a gap: the global cursor did not move because nothing was stored), and the healthcheck is `ok` again.
- **Rule:** the cursor moves only when a batch is stored, so a failed poll loses nothing ([Pull requests stored once per repository, fanned out to project links, with cursors]; [The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a lost token fails clearly, then recovers" (written, never run on a cluster). Its check that the failed tick's error text contains "Ingest failed" reads the tick error's stack and causes, and it is unconfirmed that Dagster puts that text there ([HANDOVER.md], known issues). `dagster/app/tests/test_pr_ingest_sensor.py` covers a failing repository. A lost results-repository token is in [failures mid-flow and limits](failures-mid-flow-and-limits.md).
- [ ] Pass
- [ ] Fail — notes:

## A failing task ends `FAILED`, has no result, and stays failed

1. `fncli open-pr --kind failing --merge` (a valid spec whose task exits non-zero; it needs the run image to honour `PYPIPES_EXIT_CODE`).
2. Watch the task. Wait twelve intervals.
3. Look for a result and for a second task or run for the same pull request.

- **Expected:** the task goes `FAILED` within seconds of starting; it has no result; it is not retried or relaunched on its own; the pull request stays `YIELDED`. The Dagster run is `FAILURE`.
- **Rule:** the task status mirrors the run; delivery only starts after a run succeeds; retrying a failed task is a manual action ([Task status is written by the run-status sensors and the reconcile sensor]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a failing task stays failed" (written, never run on a cluster); `dagster/app/tests/test_task_run_status_sensor.py` (a failed delivery run never patches the task). The exit code is not recorded.
- [ ] Pass
- [ ] Fail — notes:

## A task whose image cannot be started does not block the others

Needs a spec with an image name that does not exist (commit it by hand under `watch_dir`).

1. Merge that pull request, then right after it a normal watched one.
2. Watch both tasks for several minutes. Look at the task pod with `kubectl get pods -A` and `kubectl describe pod`.

- **Expected:** the normal task runs and delivers. The bad task's behaviour is not specified in the sources: record whether it stays `QUEUED` or `RUNNING` in an image-pull back-off, how long, and what status it ends with (the end-to-end suite notes that a task that fails to start can sit in a pull back-off).
- **Rule:** one failing task costs one run, not the tick ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Manual only. See also "A slow or stuck run" in [failures mid-flow and limits](failures-mid-flow-and-limits.md).
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[HANDOVER.md]: ../../HANDOVER.md
[Pull requests stored once per repository, fanned out to project links, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[Run keys, retries and the results pull request sync]: ../decisions/0015-run-keys-retries-and-results-pr-sync.md
[State transition tables for triggers, tasks and result steps; 409 on a refused move]: ../decisions/0005-state-transition-tables.md
[Task status is written by the run-status sensors and the reconcile sensor]: ../decisions/0003-task-status-written-by-run-status-sensors.md
[TaskSpec, and a Task derived from spec and trigger]: ../decisions/0002-task-spec-and-derivation.md
[The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]: ../decisions/0014-dagster-pipeline-ops-sensors-and-retries.md
