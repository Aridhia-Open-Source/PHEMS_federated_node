# Run a task and deliver the result as a pull request

The main path: a merged pull request becomes a task, the task runs, its artifacts are zipped and pushed to a branch of the results repository, and a results pull request is opened. A person merges (or closes) it and the sync sensor records that. Do this section before the failure and rule sections: they assume it works.

Needs: the dev project set up (`fncli setup-project`) with all sensors running, and the Gitea UI to look at the results repository. Check the state with `fncli project-show` (see [the index](README.md)).

## A watched pull request goes all the way to a merged results pull request

1. `fncli open-pr --kind watched --merge`.
2. Repeat `fncli project-show` until: the pull request is `YIELDED` with a `task_id`; the task goes `PENDING`, `QUEUED`, `RUNNING`, `SUCCESS`; a result appears and goes `PUSHED`, then `OPENED` (with a `number` and `url`).
3. `fncli merge-results-pr --number <the result's number>`.
4. Wait for the result to reach `MERGED`. Then `fncli verify-project` and `fncli verify-repo --tail 1`.

- **Expected:** every step above, in that order; the states only move forward. The task is `SUCCESS` whether or not the results are delivered. Both verify commands exit 0.
- **Rule:** the end-to-end flow in [docs/architecture/flows.md#end-to-end]; the result's step only moves forward ([Polymorphic Result, PullRequestResult, a forward-only step and a separate state]).
- **Automated by:** Partly automated: the end-to-end success suite (`dagster/fncli/tests/e2e/test_happy_path.py`). It passed on the dev cluster before the launch endpoint and the reconcile sensor landed; [TESTING.md](../TESTING.md#checks-that-have-never-run-on-a-cluster) lists it as not run since. Gitea only; it misses GitHub, the zip's contents and the results pull request's closing or deletion.
- [ ] Pass
- [ ] Fail — notes:

## The results branch holds the agreed layout

1. After the previous case, open the results repository in Gitea and the results pull request.
2. Open the branch and the files in it. Download `results.zip` and look inside.

- **Expected:** the branch is `<target_dir>/<trigger repository name>/<pull request number>/<task id>-<first 7 characters of the merge sha>`. Under `<target_dir>/<trigger repository name>/<pull request number>/<task id>/` are `results.zip`, `spec.json` (the task's spec) and `metadata.json` (branch, merge commit sha, task id, run id, trigger repository uri, pull request number, delivery time, zip size). The zip holds the run's artifacts. The pull request goes from the branch into the results repository's default branch.
- **Rule:** the delivery layout ([Results delivered as a pushed branch plus a results pull request]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` checks the layout against a mocked git host; the end-to-end suite checks only the steps and that a pull request was opened. Neither opens the zip.
- [ ] Pass
- [ ] Fail — notes:

## The task's status and times mirror its Dagster run

1. In the Dagster UI open the `k8s_pipes_job` run for the task (tags `trigger=task`, `task_id`, `attempt`).
2. `GET /projects/<pid>/tasks/<id>`.

- **Expected:** the task's `executor_run_id` is the run's id; its status is the run's status (`SUCCESS`); `started_at` and `completed_at` are set and match the run's times. The exit code is not recorded (the run does not expose it).
- **Rule:** the task status mirrors the run ([Task status is written by the run-status sensors and the reconcile sensor]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_run_status_sensor.py` (the mapping) and the success suite (statuses in order). They miss the times on a live run; a task that goes `STARTED` to `SUCCESS` between two ticks gets `started_at` from the run record, which is unconfirmed ([known issues](known-issues.md)).
- [ ] Pass
- [ ] Fail — notes:

## A result is delivered once

1. After a task finishes and its results pull request is `OPENED`, wait ten sensor intervals.
2. Count the results of the task (`fncli project-show`) and the branches and pull requests for it in the results repository.

- **Expected:** exactly one result for the task, one branch, one results pull request. No further attempts.
- **Rule:** the delivery run key is `deliver/<task>/<attempt>` and the result is idempotent per task and repository ([Run keys, retries and the results pull request sync]; [Polymorphic Result, PullRequestResult, a forward-only step and a separate state]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (a result past `PUSHED` is left alone) and `nexus/api/tests/test_results_and_delivery.py` (`POST` is idempotent). Restarting the sensors is in [sensors, restarts and catch-up](sensors-restarts-and-catch-up.md).
- [ ] Pass
- [ ] Fail — notes:

## A results pull request merged by hand is recorded as merged

1. Run a task to `OPENED`. In the Gitea UI merge the results pull request yourself.
2. Wait one sensor tick (30 seconds by default) and the run it launches.

- **Expected:** the result goes `MERGED` and records `merged_at` and the merge commit sha.
- **Rule:** the sync sensor records the provider's state of an opened results pull request ([Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: the success suite merges it with `fncli merge-results-pr` and waits for `MERGED` (passed on the dev cluster before the launch endpoint and the reconcile sensor landed, not run since); `dagster/app/tests/test_results_pull_request_sync.py` covers the recording. A merge in the Gitea UI is the same call to the provider; the suite misses a merge made by hand.
- [ ] Pass
- [ ] Fail — notes:

## A results pull request closed without merging is final

1. Run a task to `OPENED`. In Gitea close the results pull request without merging.
2. Wait one tick and its run. Then reopen it in Gitea and wait two more ticks.

- **Expected:** the result goes `CLOSED`, then stays `CLOSED` after the reopen (a reopened pull request is not followed). The task stays `SUCCESS`.
- **Rule:** `CLOSED` is final; the sync reads only `PUSHED` and `OPENED` results ([Run keys, retries and the results pull request sync]; [State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_pull_request_sync.py` (a closed pull request is recorded; a closed one reopened stays closed). No end-to-end test closes a pull request.
- [ ] Pass
- [ ] Fail — notes:

## A results pull request deleted on the provider stays at its last step

1. Run a task to `OPENED`. If your Gitea allows it, delete the results pull request or the branch.
2. Wait three ticks. Check `fncli sensor-status` for the sync sensor.

- **Expected:** the result stays `OPENED`; it is not guessed `CLOSED`. The sensor keeps skipping it, launches no run for it, and does not fail the other results.
- **Rule:** a 404 is logged and skipped, never guessed `CLOSED` ([Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_pull_request_sync.py` (`test_a_deleted_pull_request_is_skipped_and_the_others_still_launch`); it misses a real provider.
- [ ] Pass
- [ ] Fail — notes:

## A task that writes no artifacts fails its delivery with an error

Needs a run image that exits successfully and writes nothing to its artifact folder. Skip if you do not have one.

1. Merge a watched pull request whose spec uses that image.
2. Watch the task and the result.

- **Expected:** the task is `SUCCESS`. The delivery fails: the result is `FAILED` with an error about missing artifacts and its step is where it was; nothing is pushed. The retry sensor tries again at most once per retry interval and gives up after the maximum attempts ([task and result state machines](task-and-result-state-machines.md)).
- **Rule:** a failure is recorded as state `FAILED` with an error and an attempt; the step stays where it was ([Polymorphic Result, PullRequestResult, a forward-only step and a separate state]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_missing_artifacts_fail_the_delivery`); no end-to-end test.
- [ ] Pass
- [ ] Fail — notes:

## A task requested through the API is not delivered

Out of scope for the beta; check only so the behaviour is recorded.

1. Create a task by hand with `POST /projects/<pid>/tasks` if your node offers it (check the route and body), and let it run.

- **Expected:** the task runs and finishes. Delivery needs a task that came from a pull request, so no results pull request is opened and the delivery run fails (check).
- **Rule:** delivery needs the task to come from a pull request ([Results delivered as a pushed branch plus a results pull request]); delivery of API-requested tasks is an open question there.
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_a_task_without_a_pull_request_fails_the_delivery`). It misses a live run.
- [ ] Pass
- [ ] Fail — notes:

[docs/architecture/flows.md#end-to-end]: ../../docs/architecture/flows.md#end-to-end

<!-- link definitions -->
[Polymorphic Result, PullRequestResult, a forward-only step and a separate state]: ../decisions/0004-polymorphic-result-and-forward-only-state.md
[Results delivered as a pushed branch plus a results pull request]: ../decisions/0013-results-delivered-as-branch-and-pull-request.md
[Run keys, retries and the results pull request sync]: ../decisions/0015-run-keys-retries-and-results-pr-sync.md
[State transition tables for triggers, tasks and result steps; 409 on a refused move]: ../decisions/0005-state-transition-tables.md
[Task status is written by the run-status sensors and the reconcile sensor]: ../decisions/0003-task-status-written-by-run-status-sensors.md
