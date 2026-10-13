# 0007. Results delivered as a pushed branch plus a results pull request

- Status: Accepted (size cap and layout are tuneable)

## Context

Results of a run (files in the artifacts volume) must reach the project's results repository in a way that is reviewable by a human before it is accepted, and that survives partial failure.

## Decision

`deliver_results_job` (op `deliver_results`, class `ResultsDelivery`) delivers one task:

1. Clone the results repository (shallow) with the repository's own token.
2. The branch is `<target_dir>/<trigger repo name>/<pr number>/<task id>-<merge sha[:7]>`. If it already exists on the remote it is an earlier attempt and is not pushed again.
3. Zip the run's artifacts (`<artifact mount>/<dagster_run_id>`) as `results.zip`; fail if over `RESULTS_MAX_ZIP_BYTES` (default 10 MiB).
4. Write, next to it under `<target_dir>/<repo>/<pr>/<task id>/`: `spec.json` (the task spec) and `metadata.json` (branch, merge commit sha, task id, run id, trigger repository uri, PR number, delivery time, zip size). Commit and push the branch.
5. Record `PUSHED` with `branch` and `commit_sha`, then open a pull request from the branch into the repository's default branch (or find the one already opened for it) and record `OPENED` with `number` and `url`.

The job runs in a run pod, the only place with the artifacts volume. It is launched by a run-status sensor when the task's `k8s_pipes_job` run succeeds, once per task attempt. Delivery never changes the task's status. Currently delivery needs the task to come from a pull request (it finds the PR to build the layout), so tasks requested by API are not delivered.

## Consequences

- Results are reviewed and merged like any change; history is in git.
- Each step is recorded as soon as done, so a retry resumes: a pushed branch is reused, an opened pull request is found by branch.
- The 10 MiB cap and the layout are provisional choices; large results need another route.
- The git push uses the token in an `http.extraHeader` env, never in the URL or arguments.
- Failures are recorded as `error` and `attempts` on the result and the run fails visibly.

## Alternatives considered

- **Commit straight to the default branch**: rejected, no review step.
- **Large-file storage (DVC/object store)**: considered in earlier planning, not built.
- **Comment on the trigger PR / transfer through GitHub**: removed ([0011](0011-remove-legacy-sensors-and-github-ops.md)).
