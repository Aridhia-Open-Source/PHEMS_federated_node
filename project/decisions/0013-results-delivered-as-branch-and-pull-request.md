# 0013. Results delivered as a pushed branch plus a results pull request

## Context

Results of a run (files in the artifacts volume) must reach the project's results repository in a way that is reviewable by a human before it is accepted, and that survives partial failure.

## Decision

`deliver_results_job` (op `deliver_results`, class `ResultsDelivery`) delivers one task:

1. Ask the backend for a result (`POST /projects/<pid>/results`, the only gate, [0008](0008-enabled-revoked-and-soft-delete.md)). Where to deliver, the results repository's id and the `target_dir`, comes from the task's pinned configuration ([0009](0009-task-pinned-to-its-configuration.md)); the repository, its provider and its secret are read from the global results repository. A result that is already `REVOKED`, `STALE` or past `PUSHED` is left alone.
2. Clone the results repository (shallow) with the repository's own token.
3. The branch is `<target_dir>/<trigger repository name>/<pr number>/<task id>-<merge sha[:7]>`. If it already exists on the remote it is an earlier attempt and is not pushed again.
4. Zip the run's artifacts (`<artifact mount>/<executor_run_id>`) as `results.zip`; fail if over `RESULTS_MAX_ZIP_BYTES` (default 10 MiB).
5. Write, next to it under `<target_dir>/<repo>/<pr>/<task id>/`: `spec.json` (the task spec) and `metadata.json` (branch, merge commit sha, task id, run id, trigger repository uri, PR number, delivery time, zip size). Commit and push the branch.
6. Record step `PUSHED` with `branch` and `commit_sha`, then open a pull request from the branch into the repository's default branch (or find the one already opened for it) and record the step it is at (`OPENED`, or `MERGED`/`CLOSED` if an earlier attempt's pull request is already finished), the state `DELIVERED`, and `number`, `url`.

The job runs in a run pod, the only place with the artifacts volume. It is launched by a run-status sensor when the task's `k8s_pipes_job` run succeeds, once per task attempt, and by the retry sensor for failed deliveries ([0015](0015-run-keys-retries-and-results-pr-sync.md)). Delivery never changes the task's status. Delivery needs the task to come from a pull request (it finds the pull request to build the layout), so a task requested by API is not delivered.

## Consequences

- Results are reviewed and merged like any change; history is in git.
- Each step is recorded as soon as done, so a retry resumes: a pushed branch is reused, an opened pull request is found by branch.
- The 10 MiB cap and the layout are tuneable; large results need another route.
- The git push uses the token in an `http.extraHeader` env, never in the URL or arguments.
- A failure is recorded as state `FAILED`, `error` and one more `attempt` on the result, the step stays where it was, and the run fails visibly ([0004](0004-polymorphic-result-and-forward-only-state.md)).
- The outcome (a `REJECTED` cause, a link to the results) is not commented back on the trigger pull request.
- The pull request's later merge or close is found by the sync reconciler ([0015](0015-run-keys-retries-and-results-pr-sync.md)).

## Alternatives considered

- **Commit straight to the default branch:** no review step.
- **Large-file storage (DVC or an object store):** the zip in git is simpler for the sizes in scope.
- **Comment on the trigger pull request, or transfer through GitHub:** keeps delivery tied to one provider.

## Open questions

- Delivery of results of API-requested tasks.
- Commenting the outcome on the trigger pull request.
- A route for results over the size cap.
