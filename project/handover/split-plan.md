# Split plan: moonshot/shared-resources into stacked PRs (cheap, by path)

Status: planned, not executed (2026-10-18). Run it once e2e (happy path and failure suite) is mostly green and `moonshot/soft-delete` has landed.

## Approach

Split the final tree by path, not by history. Each PR takes a group of files from the final commit of `moonshot/shared-resources`, stacked on the previous one. Only the top of the stack is guaranteed green; the lower PRs are for reading. Review goes bottom up; merge the whole stack into `dagster-develop` together (or merge the top PR, which contains everything).

- Base: `origin/dagster-develop` (`583fabf5`, the current merge base).
- Size today: 342 files, +27.6k / -14.8k lines (`git diff --shortstat origin/dagster-develop...moonshot/shared-resources`).

## The stack

| # | Branch | Paths | What the reviewer looks at |
|---|---|---|---|
| 1 | `split/01-schema` | `webserver/migrations/`, `webserver/app/models/`, `webserver/app/helpers/state_rules.py`, `webserver/app/helpers/soft_delete.py`, `webserver/tests/test_state_rules.py` | Baseline schema (one migration), enums and transition tables, soft delete mixin |
| 2 | `split/02-webserver` | `webserver/` (everything else: routes, DTOs, helpers, `static/openapi.json`, tests, build and test config) | ADR 0006, 0008, 0009 and 0011 rules: fan-out and `skip_gap`, config pinning, results gate, revoke and delete, filters |
| 3 | `split/03-dagster` | `dagster/app/`, `pypipes/` | Sensors and ops: ingest op, evaluate, launcher, run status, delivery and its retry sensor, sensor helpers |
| 4 | `split/04-fncli-e2e` | `dagster/fncli/`, `scripts/fncli/`, `scripts/e2e_*` | fncli commands, simulation, e2e happy and failure suites |
| 5 | `split/05-deploy` | `k8s/`, `scripts/` (rest), `dev.db/`, Tiltfile and Makefile changes if any | Helm values (sensor interval, retry interval, max attempts), deploy owner guard, dev tooling |
| 6 | `split/06-docs` | `project/`, `docs/` | the ADRs, flow docs, handovers |

Anything not matched by 1-5 falls into 6; check `git status` after step 5 for stragglers.

## Commands (to run later)

```bash
FINAL=$(git rev-parse moonshot/shared-resources)
BASE=origin/dagster-develop
git switch -c split/01-schema "$BASE"        # in a fresh worktree, never the main checkout
git checkout "$FINAL" -- webserver/migrations webserver/app/models webserver/app/helpers/state_rules.py webserver/app/helpers/soft_delete.py webserver/tests/test_state_rules.py
git commit -m "Split 1/6: schema, enums, transition tables, soft delete"
git switch -c split/02-webserver && git checkout "$FINAL" -- webserver && git commit -m "Split 2/6: webserver rules and routes"
git switch -c split/03-dagster   && git checkout "$FINAL" -- dagster/app pypipes && git commit -m "Split 3/6: Dagster sensors and ops"
git switch -c split/04-fncli-e2e && git checkout "$FINAL" -- dagster/fncli scripts/fncli scripts/e2e_shared_resources.sh scripts/e2e_check.py && git commit -m "Split 4/6: fncli and e2e"
git switch -c split/05-deploy    && git checkout "$FINAL" -- k8s scripts dev.db && git commit -m "Split 5/6: chart and dev tooling"
git switch -c split/06-docs      && git checkout "$FINAL" -- . && git commit -m "Split 6/6: docs and ADRs"
git diff "$FINAL" split/06-docs --stat       # must be empty
```

Deleted files: `git checkout FINAL -- <dir>` does not delete files that FINAL removed. Before each commit run `git diff --name-only --diff-filter=D "$BASE" "$FINAL" -- <paths> | xargs -r git rm -q` for that step's paths.

Then one PR per branch, each targeting the previous branch (PR 1 targets `dagster-develop`). Push with the explicit GitHub URL (the `origin` push URL is a guard).

## Not done (cheap split)

- Lower PRs are not tested on their own.
- No new review guide; reviewers start from ADR 0008 (enabled, revoked, soft delete), ADR 0015 (run keys and retries), ADRs 0011, 0005 and 0014 and `docs/architecture/flows.md`.
