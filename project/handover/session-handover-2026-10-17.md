# Session handover, 2026-10-17 (cloud session): what to review and where things are

Pointer note. Read `project/moonshot-as-built.md` (status at the top) first for the backend's state.
**Nothing from the cloud session has been run** (no cluster, and the owner said not to run tests there). Everything below needs a laptop run.

## Branches that need review

- **`moonshot/e2e-failure-suite`** (off this branch; about 10 commits and roughly 100 lines of application code on top of it, plus tests and tooling). Review in this order:
  1. `project/handover/e2e-failure-suite-handover.md` on that branch: what it holds and what to check first.
  2. **Application code (small, behaviour changing):**
     - `REVOKED` result step: `POST /results` through a revoked results link creates the result as step `REVOKED`, state `FAILED` (201, it was 409), final. Webserver `results_api.py`, models, openapi; Dagster `delivery/results.py` leaves it alone.
     - `skip_gap`: when a global `TriggerRepository` or a `GitProvider` is switched back on, every link's cursor moves to now, so PRs merged while it was off are stored by the catch-up but get no trigger. `helpers/pull_request_fanout.py`, `trigger_repositories_api.py`, `git_providers_api.py`. Link enable and un-revoke still backfill.
     - `pypipes/main.py` exits with `PYPIPES_EXIT_CODE` (the image must be rebuilt); `fncli open-pr --kind failing` uses it.
  3. **Tests and tooling (never run):** the e2e failure suite (`dagster/fncli/tests/e2e/test_failure_paths.py`, S3 to S6, S5 again, S10, S11, S12, S13; run with `pytest dagster --e2e failure -v`; the sensor interval is patched to 1 s and restored; `E2E_TEARDOWN=1` tears down at the end); the multi-provider simulation (`fncli simulate-setup | simulate-run | simulate-check | simulate-teardown`, logic in `dagster/fncli/simulation.py`); the Hypothesis rule set for the trigger link (`webserver/tests/test_stateful_rules.py`, the docstring lists the rules M1 to M6 to review; `hypothesis` is in `pyproject.toml` dev extras, `requirements-dev.txt` still needs regenerating).
- **`moonshot/gitea-mirror`**: parked for the beta; see its `session-handover-2026-10-17.md`.
- `moonshot/dagster-sensors`: redundant, its work is merged here. Delete it with the other leftover remote branches.

## Decisions made in the session

- A PR merged while a link is switched off or revoked: a link that is enabled or un-revoked backfills it (self-healing at link level). A global repository or provider switched back on skips the gap instead (no trigger, no `IGNORED` state). Open: whether links should work the same way as the global repo (no backfill).
- A results link revoked mid-task: the task finishes, nothing is delivered, the result is `REVOKED` and final. Killing a running task is post-beta. Decision 5 is confirmed.
- The lock and drained rules stay. Their e2e scenarios (S7, S8, S9, S16) were dropped in favour of unit tests.
- **Known gap, accepted, post-beta:** the lock check and the change are two steps; `post_task` does not check the project is unlocked, so a task can slip in between. Worst case it fails or is not delivered. Fix: 409 for a locked project in `post_task`, plus a `SELECT ... FOR UPDATE` on the project in `require_drained` and `post_task`. See ADR 0019, Consequences.
- Known edge of `skip_gap`: a PR merged shortly before the switch-off and not yet ingested is also skipped; the exact fix is a `disabled_at` column.
- Postgres row and advisory locks cannot replace the project lock (a transaction is too short); they only fit the check-then-change race.

## What is left for the beta (from the open issues #501, #536 to #542; the boxes there look stale, not checked against the code)

- #537 pipeline resilience: one bad task stops every launch (the launcher errors out for all tasks), marked required for beta.
- #536 task isolation: no NetworkPolicy, cluster-wide RBAC, no per-task Secrets or pod security settings, hung tasks stay `RUNNING` for 24 hours, artifact folders never removed.
- #539 auth rewrite (the auth plan in `project/auth-mvp-plan.md` assumes user ⊂ admin ⊂ system; the owner's decision is super user and system user only for now).
- #538 task attempts table and forward-only run status; #500 deployment check (the gate); #493 secrets and datasets follow-ups.
- Not in the issues: revoked secret link still used at token read; the ingest versus link-create race; `get_or_assign_*` returning an existing link with different settings; Dagster code-server restart after a credential rotation; decisions 7 and 8 unconfirmed.

## First things to do on the laptop

1. Rebuild the images; run `webserver/run_tests.sh` and `dagster/run_tests.sh` (the changes since the last green run are about 100 lines of app code, mostly the revoked-result path and `skip_gap`).
2. Run the Hypothesis rule set and read the rules (M2 and M6 changed after the owner's decisions).
3. `pytest dagster --e2e failure -v`, then the simulation.
4. Laptop-only: delete the leftover remote branches and push the tag `shared-resources-tests-full` at `ee653cd2` (the cloud proxy refuses both).
