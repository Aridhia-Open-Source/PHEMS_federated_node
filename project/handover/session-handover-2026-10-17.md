# Session handover, 2026-10-17 (cloud session): where the in-flight moonshot work is

Pointer note. Read `project/moonshot-as-built.md` (status at the top) first for the backend's state.

## Branches

- `moonshot/shared-resources` (this one): the backend's work. GitProvider, routes moved, projects start locked, one sensor interval from
  Helm, Dagster sensor items 1 to 3 and 5. The happy path is proven live on `kind-fn`.
- `moonshot/e2e-failure-suite` (off this branch, **not merged**): the e2e failure suite and the `REVOKED` result step. Start with
  `project/handover/e2e-failure-suite-handover.md` on that branch. Nothing on it has been run.
- `moonshot/gitea-mirror`: parked for the beta. See its `project/handover/gitea-mirror-plan.md`.
- `moonshot/dagster-sensors`: redundant, its work is merged here. Delete it with the other leftover remote branches.

## Decisions made in the session (all implemented on the e2e branch, none merged here yet)

- A PR merged while a link or repository was switched off is picked up when it is back on (self-healing). Not yet verified against the code;
  needs a webserver test on the `TriggerRepository` cursor.
- A results link revoked mid-task: the task finishes, nothing is delivered. The `PullRequestResult` is created with step `REVOKED`, state
  `FAILED`, and `REVOKED` is final. `POST /results` through a revoked link returns 201 (it was 409); other inactive links still 409.
  Killing a running task is post-beta. Decision 5 is confirmed.
- The failing-task e2e case uses an image that exits non-zero (`PYPIPES_EXIT_CODE`), not a bad image name.
- The e2e project is cleared at the start of a run and kept afterwards; `E2E_TEARDOWN=1` tears it down.
- The lock and drained rules stay (they are the safety rule); their e2e scenarios (S7, S8, S9, S16) were dropped in favour of unit tests.
- Postgres row and advisory locks are not a replacement for the project lock; they could harden its check-then-change race after the beta.

## Open

Run the unit tests and the e2e failure suite on the laptop; the self-healing test; the bug review (migrations 002 to 004, lock and drain,
sensors); auth (the plan assumes user ⊂ admin ⊂ system, the decision is super user and system user only); Dagster RBAC narrowing and the
code-server restart after credential rotation; decisions 7 and 8 still unconfirmed; the as-built refresh. Laptop-only: delete the leftover
remote branches and push the tag `shared-resources-tests-full` (the cloud proxy refuses both).
