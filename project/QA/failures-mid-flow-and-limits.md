# Failures mid-flow and limits

What happens when a service goes down part-way through, a token expires or is replaced, several pull requests arrive at once, or a limit is reached. Almost none of this is automated: the unit tests mock the other side, and the end-to-end suites test one lost token and nothing else. Treat every case as a search for a stuck item: a task `PENDING` or `RUNNING` forever, a pull request with no trigger, a `SUCCESS` task with no result, a result that no sensor will pick up.

The sources say the design is "event-driven and reconciling": sensors act on a view of the state that may be stale, every write goes through the state tables, and a failing item costs one run or one log line, not the tick ([Responsibility: nexus-api owns the record and the rules; Dagster carries out decisions]; [The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]). Where a case says "the sources do not say", write down what you see.

Needs: `kubectl`, `fncli`, the Dagster UI, the dev project with sensors running. These cases stop and restart services; do them on the test node only, one at a time, and put everything back (`kubectl scale ... --replicas=1`). Deployment names differ per release: list them with `kubectl get deploy -A` (check). A lost or replaced results token is in [task and result state machines](task-and-result-state-machines.md); a lost trigger token is in [failure paths](failure-paths.md).

## nexus-api is unavailable for a few minutes while the sensors tick

1. Merge a watched pull request and, when its task is `RUNNING`, scale nexus-api deployment to zero. Merge another watched pull request.
2. Wait five intervals. `fncli sensor-status` and the Dagster UI tick logs.
3. Scale nexus-api back up. Wait ten intervals.

- **Expected:** while it is down, ticks fail or skip with an error naming nexus-api; nothing is created; no sensor stays broken. After step 3 the sensors recover with no manual action, the second pull request is processed once, the first task reaches its final status (the reconcile sensor repairs it if the run-status sensors missed it) and no pull request, trigger or task is duplicated. A launch call that fails leaves its task `PENDING`; the next tick retries it.
- **Rule:** an error leaves the item for the next tick; the run key makes a repeat harmless ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_launcher.py` (an error leaves the task `PENDING` and is retried), `dagster/app/tests/test_sensor_base.py` (a failing item does not stop the others). They mock nexus-api; a real outage, with real HTTP errors and a recovering client, is not tested.
- [ ] Pass
- [ ] Fail — notes:

## nexus-api is unavailable at the moment a task finishes

Check: this may leave a `SUCCESS` task with no result. Record what you see.

1. Merge a watched pull request. Wait until the task is `RUNNING`. Scale nexus-api to zero just before it ends (a task that takes about a minute makes this easier).
2. Leave it down for three intervals while the run finishes. Scale it back up.
3. Wait ten intervals. `fncli project-show`; look at the delivery run in the Dagster UI.

- **Expected:** the sources do not say. The delivery job's first call is `POST /projects/<pid>/results`; if it fails the run fails before a result exists, and the retry sensor only retries results that are already `FAILED`. If the task ends `SUCCESS` with no result and no later delivery, record it as a finding. If a result appears, note which sensor and run delivered it.
- **Rule:** the retry sensor lists `FAILED` results on active project resources ([Run keys, retries and the results pull request sync]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## The database restarts or is unavailable

1. With a task `RUNNING` and a pull request about to be merged, delete the Postgres pod (or scale it to zero for a few minutes). Merge a watched pull request meanwhile.
2. Bring it back. Wait ten intervals.

- **Expected:** while it is down nexus-api returns errors (note which) and the sensors' ticks fail without creating anything. After it returns nothing needs repairing by hand: counts match what was merged, no half-written pull request, task or result (compare `stored_pr_count`, pull requests and tasks), and the pipeline continues.
- **Rule:** nexus-api owns the record; a failed write leaves no partial state ([Responsibility: nexus-api owns the record and the rules; Dagster carries out decisions]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## The git host (Gitea) is unavailable during ingest

1. Scale Gitea to zero and let the sensors tick for five intervals with it down.
2. Watch the Dagster Runs page for ingest runs and `fncli sensor-status`.
3. Scale Gitea back up. Merge a watched pull request. Wait.

- **Expected:** the ingest sensor's check fails each tick, naming the repository; nothing is created; the other sensors keep ticking. No more than one failed ingest run per repository per retry interval. After step 3 the new pull request is processed once.
- **Rule:** a failing repository is logged and the others still launch; the cursor moves only when a batch is stored ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Partly automated: `dagster/app/tests/test_pr_ingest_sensor.py` (a failing repository does not stop the others; the tick fails when nothing launched) and `dagster/app/tests/test_sensor_base.py`. The end-to-end failure suite covers a lost token, not an unreachable host.
- [ ] Pass
- [ ] Fail — notes:

## The git host is unavailable during delivery and recovers within the attempts

1. Merge a watched pull request. When the task is `RUNNING`, scale Gitea to zero.
2. Let the task finish. Watch the result for three retry intervals.
3. Scale Gitea back up. Wait.

- **Expected:** the delivery fails and the result is `FAILED` with an error and the step where it was (or no result exists yet: record which); the task stays `SUCCESS`. After Gitea returns the retry sensor delivers it within the attempts: step `OPENED`, state `DELIVERED`, one branch, one results pull request.
- **Rule:** a failure is recorded as state `FAILED` with an attempt and the step stays; the retry resumes ([Results delivered as a pushed branch plus a results pull request]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (a git failure records the error and raises; a retry delivers). No end-to-end test; the real outage and timing are not tested.
- [ ] Pass
- [ ] Fail — notes:

## The git host is unavailable while the results pull request sync runs

1. Run a task to `OPENED`. Scale Gitea to zero for three intervals. Scale it up. Merge the results pull request.

- **Expected:** while it is down the sync run fails (a provider error other than 404 fails the run) and the result stays `OPENED`; after it returns the result goes `MERGED`. No result is guessed `CLOSED`.
- **Rule:** a 404 is skipped; any other provider error fails the run and the next slot retries ([Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_pull_request_sync.py` (`test_a_provider_error_other_than_404_fails_the_sync`). It misses a real provider outage.
- [ ] Pass
- [ ] Fail — notes:

## A delivery run is killed part-way

Check: the sources do not say what a killed delivery leaves behind.

1. Merge a watched pull request. When the delivery run starts (Dagster UI, `deliver_results_job`), delete its run pod.
2. Wait ten intervals. `fncli project-show` and the results repository in Gitea.

- **Expected:** the result may be missing, `PUSHED` without a pull request, or `FAILED`. If it is `FAILED` the retry sensor resumes it. If it is `PUSHED` with no pull request, or has no row at all, check whether any sensor ever picks it up (the sync sensor reads `PUSHED` results and records a pull request only if one exists; the retry sensor reads only `FAILED`). Record the outcome.
- **Rule:** each step is recorded as soon as it is done, so a retry resumes ([Results delivered as a pushed branch plus a results pull request]).
- **Automated by:** Manual only. The unit tests raise errors inside the job; none kill the process.
- [ ] Pass
- [ ] Fail — notes:

## A task pod is killed mid-run

1. Merge a watched pull request. When the task is `RUNNING`, delete the task pod (`kubectl get pods -A`, in the task namespace).
2. Wait five intervals.

- **Expected:** the Dagster run ends `FAILURE`, the task goes `FAILED`, no result is made, and it is not relaunched on its own (the run key for that attempt is used). Record the cause shown on the task, if any.
- **Rule:** the task status mirrors the run; a retry bumps the attempt ([Task status is written by the run-status sensors and the reconcile sensor]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_run_status_sensor.py` (the mapping of a failed run). No test kills a pod.
- [ ] Pass
- [ ] Fail — notes:

## Keycloak is unavailable, then returns

1. Scale Keycloak to zero for three intervals while the sensors tick. Scale it back.
2. Wait ten intervals. Log in as the administrator and run `fncli project-show`.

- **Expected:** while it is down, logins and the sensors' backend calls fail; no state is created; the sensors do not stay broken. After it returns, ticks succeed again with no restart, and new logins work.
- **Rule:** the Dagster client logs in and refreshes its token on a 401, 403 or 429 (the code is in `dagster/app/utils.py`; no decision record describes it, check).
- **Automated by:** Partly automated: `dagster/app/tests/test_utils.py` (auth failures refresh the token and retry; a still-failing retry is returned, not looped). A real Keycloak outage is not tested.
- [ ] Pass
- [ ] Fail — notes:

## Tokens expire and are refreshed while sensors run

Needs a short token life: the chart value `token.life` (seconds). Lower it on the test node, redeploy, and put it back afterwards.

1. With a short life (for example a few minutes), keep the sensors running for several times that life and merge a watched pull request after each expiry.
2. Watch `fncli sensor-status` and nexus-api logs for authentication errors.
3. Start a task that outlives one token life and let it deliver.

- **Expected:** after each expiry the Dagster client refreshes its token (on a 401, 403 or 429, with a back-off) and ticks go on succeeding; each pull request is processed once; a long task and its delivery complete. Record any tick that fails with an authentication error before recovering.
- **Rule:** the Dagster backend client authenticates as a Keycloak System user ([Authorization detached from DAR, Keycloak and whitelisted images]) and refreshes its token on a 401, 403 or 429 (the code is in `dagster/app/utils.py`; check).
- **Automated by:** Partly automated: `dagster/app/tests/test_utils.py`, `dagster/app/tests/test_backend.py` (refresh on 401/403/429, a refresh token is preferred). The tests use a fake session; real expiry timing is not tested.
- [ ] Pass
- [ ] Fail — notes:

## A rotated trigger token is picked up without a restart

1. Note that the sensors run. `fncli init-git-secret --entity trigger` (writes a fresh token into the Secret), then `fncli verify-git-secret --entity trigger`.
2. Merge a watched pull request. Wait.

- **Expected:** the next ingest tick uses the new token; no restart of the code server is needed; the pull request is processed once. If ingest fails with an authentication error, record how long it takes to recover. (The decision lists that the code server is not restarted after a credential rotation as an open question.)
- **Rule:** the git client reads the repository's own token each time it is built ([GitAPI protocol and GitAPIFactory over Gitea and GitHub]; [Generic Secret model and SecretProvider; per-repository tokens]).
- **Automated by:** Partly automated: `dagster/app/tests/test_git_api_factory.py` (`test_the_token_is_read_from_the_repository_secret`) and `dagster/app/tests/test_secrets.py`. A live rotation is not tested.
- [ ] Pass
- [ ] Fail — notes:

## Several pull requests merged at once are each processed once

1. Note the counts. Create five branches with `fncli create-gitea-branch`, `fncli commit-gitea-file --branch <b> --kind watched` and `fncli create-gitea-pr --branch <b>` for each, then merge all five as close together as you can (several terminals, or a loop that backgrounds each `fncli merge-gitea-pr --number <n>`).
2. Wait until everything settles. Compare the counts.
3. Optionally repeat with twenty.

- **Expected:** the stored count and the pull request count are each up by five, the task count is up by five, each pull request has exactly one trigger and one task, no duplicate, no `REJECTED`. Five results. Pull requests merged in the same second keep a stable order (merge time, then number).
- **Rule:** a pull request is unique by repository and number and by repository, base branch and merge commit; one task per trigger; the cursor orders by `(merged_at, number)` ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_ingest_fans_out_and_is_idempotent`, the cursor and merge-commit tests) test a batch posted at once; `dagster/app/tests/test_ingest_job.py` the batching. Real parallel merges and parallel runs are not tested.
- [ ] Pass
- [ ] Fail — notes:

## Results over the size limit fail the delivery and push nothing

Needs a task image that writes more than the limit (10 MiB zipped by default; `RESULTS_MAX_ZIP_BYTES`, a Dagster setting; check where it is set on your release). Skip if you have none.

1. Merge a watched pull request whose task writes more than the limit.
2. Watch the task and the result for ten intervals.

- **Expected:** the task is `SUCCESS`. The delivery fails with an error about the size and nothing is pushed (no branch). The result is `FAILED` and is retried until the attempts run out, failing each time; nothing alerts. Raising the limit and restoring the setting would let a retry deliver (check; do not rely on it).
- **Rule:** the zip is capped; large results need another route ([Results delivered as a pushed branch plus a results pull request]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_over_the_cap_fails_the_delivery_and_pushes_nothing`) and `dagster/app/tests/test_config.py` (the default and the environment override). No live run with a large result.
- [ ] Pass
- [ ] Fail — notes:

## A slow or stuck run

Needs an image that sleeps for a long time, or a spec with an image that cannot be pulled.

1. Merge a watched pull request with that spec, and then a normal watched one.
2. Watch both tasks for several minutes.
3. Terminate the stuck run in the Dagster UI.

- **Expected:** the normal task runs and delivers. The slow task stays `RUNNING` (or `QUEUED` in an image-pull back-off); the sources document no timeout, so record how long it sits. After step 3 it goes `CANCELED` and no result is made. Other projects and tasks are unaffected.
- **Rule:** a failing or slow item costs one run, not the tick; a canceled run ends `CANCELED` ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Authorization detached from DAR, Keycloak and whitelisted images]: ../decisions/0017-authorization-detached-from-dar-and-keycloak.md
[Generic Secret model and SecretProvider; per-repository tokens]: ../decisions/0007-secrets-and-secret-providers.md
[GitAPI protocol and GitAPIFactory over Gitea and GitHub]: ../decisions/0010-git-api-protocol-and-factory.md
[Pull requests stored once per repository, fanned out to project resources, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[Responsibility: nexus-api owns the record and the rules; Dagster carries out decisions]: ../decisions/0021-nexus-api-owns-the-record-and-the-rules.md
[Results delivered as a pushed branch plus a results pull request]: ../decisions/0013-results-delivered-as-branch-and-pull-request.md
[Run keys, retries and the results pull request sync]: ../decisions/0015-run-keys-retries-and-results-pr-sync.md
[Task status is written by the run-status sensors and the reconcile sensor]: ../decisions/0003-task-status-written-by-run-status-sensors.md
[The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]: ../decisions/0014-dagster-pipeline-ops-sensors-and-retries.md
