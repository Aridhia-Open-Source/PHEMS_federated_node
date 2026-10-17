# Handover: e2e failure suite, REVOKED results, what is next

Branch `moonshot/e2e-failure-suite` (head `1d4849a3` plus this note), based on `moonshot/shared-resources`. **Nothing on this branch has been
run.** No e2e (no cluster in the cloud session), no webserver or Dagster unit tests (the owner said never run tests in the cloud session
unless told). It compiles. Expect small fixes on the first laptop run.

## What is on the branch

- **e2e failure suite** (`dagster/fncli/tests/e2e/test_failure_paths.py`, `pytest dagster --e2e failure -v` from the repo root):
  S3 to S6, S5 twice, S10, S11, S12, S13, then teardown. **S7, S8, S9 and S16 were dropped from e2e** (the lock and drained rules, a
  disabled global repository, the results link revoked mid-task): they need the lock and a task caught in flight, so they belong in unit and
  integration tests. Still to write: a webserver test that the `TriggerRepository` cursor does not move while it is disabled and a PR
  merged in the gap is ingested once it is back on (the self-healing rule, which is **not yet verified against the code**).
  - Sensor interval is patched to 1 s for the run and restored after (ConfigMap `dagster-env-config` plus a code-server restart,
    `fncli/k8s.py`). `E2E_KEEP_INTERVAL=1` skips it. The restart stops the sensors; the suite starts them again.
  - "Nothing happens" checks wait for 5 new ticks of ingest, evaluate and launcher (`quiet_wait`, via the Dagster GraphQL tick query), so a
    stopped sensor fails the check instead of passing it.
  - The project is cleared at the start of every run and **kept** afterwards. `E2E_TEARDOWN=1` also tears it down at the end (both suites).
  - `E2E_TASK_TIMEOUT` (default 600 s) overrides the task timeout.
- **Owner decisions implemented**
  - S9: a PR merged while the global repository was off is ingested once it is back on (self-healing, asserted). ADR 0019 now says so.
  - Revoked results link mid-task: the task runs to the end and nothing is delivered. Killing a running task is post-beta.
    `POST /results` through a revoked link creates the result as step `REVOKED`, state `FAILED` (201). `REVOKED` is final: un-revoking does
    not deliver it. A link inactive for another reason (disabled, global repo off) still gives 409. This confirms decision 5.
  - S12: a failing task is a valid spec whose task exits non-zero. `pypipes/main.py` exits with `PYPIPES_EXIT_CODE`;
    `fncli open-pr --kind failing` sets it. **The `pypipes-fn` image must be rebuilt** (Tilt does it). A bad image is not used.
- **REVOKED code:** webserver `models/pull_request_result_step.py`, `models/pull_request_result.py`, `results_api.py`, `openapi.json`;
  Dagster `models/pull_request_result_step.py`, `delivery/results.py`; unit tests in `webserver/tests/test_results_and_delivery.py` and
  `dagster/app/tests/test_results_delivery.py` (edited, not run). No migration: `step` is a plain string column.
- **Docs:** ADR 0019 (decision 13, self-healing), ADR 0008, `docs/architecture/entities.md`, `project/handover/e2e-qa-plan.md` (S12 uses `--kind failing`).

## Simulation (added after the failure suite)

`fncli simulate-setup | simulate-run | simulate-check | simulate-teardown`: four projects over two `GitProvider`s (one Gitea, a second
host name through an ExternalName service) and several trigger and results repositories, PRs merged concurrently, end state checked per
project and repository. See `dagster/fncli/README.md`. Unit tests: `dagster/fncli/tests/test_simulation.py`. **Never run**, including its
unit tests. Assumptions to check on the laptop: the ExternalName alias reaches Gitea from the Dagster code server and the webserver;
the sensors need no dataset on the projects; two projects delivering results from one trigger repository to different results
repositories do not collide. Next: an outage step, then retries.

## First things to do on the laptop

1. Rebuild the images, run the webserver tests (`webserver/run_tests.sh`) and the Dagster tests (`dagster/run_tests.sh`).
2. `pytest dagster --e2e failure -v`. Watch these in particular:
   - **S11** asserts an ingest tick fails with "Ingest failed". That comes from reading `pr_ingest.py` (it raises when a repo fails), not from a run.
   - **S10** assumes two projects delivering to the same results repository do not collide, and that deleting `QaTwo` returns 204.
   - **S12** needs the rebuilt image, or the task succeeds and the test times out.
   - 5 ticks at 1 s may be 5 s of real time, because the daemon ticks later than the minimum. Raise `QUIET_TICKS` if the negative checks pass too easily.
3. A failure leaves the project in place (by design); the next run clears it.

## Known gaps and not done

- S14 (teardown then set up again) is covered only by the start-of-run teardown and setup; S15 (known gaps) is not automated.
- Delivery with no results link is deliberately not handled for the MVP (comment in Dagster).
- The 16 files my lint auto-fix touched were reverted; do not run `ruff --fix` over `dagster/fncli` without checking the diff.
- The earlier `fncli` unit-suite run in the cloud session was killed before finishing, so the 365 fncli unit tests were never run on this branch.

## Where the project is

- `moonshot/shared-resources` has the backend's work: GitProvider, routes moved, locked-by-default projects, sensor interval from Helm,
  the Dagster sensor items 1 to 3 and 5 (ingest batching and per-repo isolation, 409 as skip, filters on the webserver, disabled secret
  refused). The happy path is proven live on `kind-fn`.
- **Still open:** Dagster RBAC narrowing and the code-server restart after credential rotation; the sensor redesign (per-PR job, delivery
  as an op, mirror webhook), best after the beta; the narrow bug review the backend asked for (migrations 002 to 004, lock and drain rules,
  sensors); auth (`project/auth-mvp-plan.md` assumes user ⊂ admin ⊂ system, but the owner's decision is super user and system user only
  for now, so reconcile it first); the as-built document refresh.
- **Owner's laptop tasks:** delete the redundant remote branches (`shared-resources-routes`, `shared-resources-tests`, `fncli-e2e`,
  `gitea-mirror-fixes`, `adr-0019-decisions`, `build-plan`, `stage-0-contracts`, `dagster-sensors`) and push the tag
  `shared-resources-tests-full` at `ee653cd2`; the cloud session's proxy refuses ref deletion and tag pushes.
- **Next, undecided:** the owner asked for sub agents to split further work (bug review, auth, Dagster items, or a fresh review of this
  branch) in a branch off `moonshot/shared-resources`, with no tests run by the agents. Which work was not chosen.

## Working rules the owner set

Terse answers, lead with the answer. Do not run anything unasked; never run tests in the cloud session unless told. Auth, audit and
normal-user permissions are out of scope. Never `make teardown` the owner's dev cluster.
