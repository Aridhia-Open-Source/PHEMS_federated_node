# Handover for the laptop, 2026-10-18 (after the review stack and the decision records)

Written by the cloud session. Nothing here has been run on a cluster. Where the cloud session was unsure, it says so and the item is under "Decide or verify".

## What exists

- **Review stack:** draft PRs #555 to #561 (branches `split/01-schema` to `split/07-tests` over `split/00-base` = `dagster-develop` without tests). Cut from `moonshot/shared-resources` `c55984fb`; the top has the same code plus the decision records. Start from `project/handover/review-guide-shared-resources.md` (on the stack tip, `split/06-docs`). CI does not trigger on `split/*` bases. There is no route into `dagster-develop` yet.
- **Decision records:** ADR 0019 is now an umbrella; 0021 to 0028 hold one major change each (on `split/01..06`, all on the tip). Each ends with "Not built or open". Rebuilding the stack if `shared-resources` moves: re-cut the branches by path as in `project/handover/split-plan.md`, then re-add the records (they are plain files).
- **`moonshot/e2e-run1-fixes`** (not merged, no PR): fixes for the first live e2e run (`started_at` taken from the run record, an admin login for `link-set --revoked`, the S11 error text, the fast-sensors config). See `project/handover/e2e-run1-fixes.md` on that branch.
- Unit tests at the stack tip (hand runs): webserver 812 passed (1 skipped), deep Hypothesis passed, Dagster app 377, fncli 139.

## Do first

1. Merge or cherry-pick `moonshot/e2e-run1-fixes`, set `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD` in `.dev.env`, rebuild, and re-run the success suite then the failure suite (`pytest dagster --e2e success|failure -v`, from the repo root, `.dev.env` exported). S6, S5b and S10 were not run last time.
2. Fix the `keycloak-realm-init` crash loop after deploy (realm migration 2: "client profile contains the executor which does not have valid provider").
3. Decide the code issues below and update the records to match whichever way each goes.

## Code issues found by checking the records against the code (not fixed)

| # | Issue | Where | Suggested fix |
|---|---|---|---|
| 1 | A **deleted dataset link leaves its task `PENDING` for ever**: `get_project_dataset` gets a 404, the launcher logs it and retries every tick | `dagster/app/definitions/sensors/task/launcher.py`, the route hiding deleted rows | treat a 404 as a failure and set the task `FAILED` naming the dataset |
| 3 | `fncli link-set --revoked` is refused (403): `g.caller_is_admin` is `"Administrator" in roles`, the Dagster user has `System` | `webserver/app/helpers/keycloak.py` `is_user_admin` | the fncli admin login (done on the fixes branch), or accept `System` (lets a pipeline credential revoke grants) |
| 4 | `config_hash` is stored and returned but never compared | `helpers/task_config.py` | use it as a quick equality check before the diff, or drop the column |
| 5 | Delivery takes only the repository id and `target_dir` from the snapshot; the repository, provider and secret are read live | `dagster/app/delivery/results.py` | decide if that is intended (credentials must stay live) and say so in 0024 |
| 6 | A PR merged just before a switch-off and not yet ingested is also skipped on switch-on | `helpers/pull_request_fanout.py` `skip_gap` | a `disabled_at` timestamp; cursor moves to it, not to now |
| 7 | The cross-project loop check keys on `(provider_id, repo_path)`: the same server under two host names is not seen | `helpers/repository_loop.py` | leave, or resolve hosts |
| 8 | A link's `active` ignores the secret; only the `pollable` filter uses it | `GitRepositoryMixin.active` | decide whether `active` should include the secret |
| 10 | Stale text: `ResultState` docstring says nothing retries `FAILED` but the retry sensor does | webserver models | edit the comments |
| 11 | Retrying a task that cannot be retried is a 400; the other refused moves are 409 | `tasks_api.py` `retry_task` | pick one |
| 12 | The webserver calls Dagster (`/dagster/sensors` routes, `helpers/dagster.py`); ADR 0019 used to say it does not | `webserver/app/dagster_api.py` | keep as an operator convenience, or move it out |

## Decide or verify (the cloud session was unsure)

- Dataset `PATCH` returns 200, and `GET /tasks` clamps `page` and `per_page` below 1: both still marked unconfirmed in ADR 0019.
- `started_at` fix: does Dagster fill `start_time` for a run that goes STARTED to SUCCESS between two ticks? If not, the fix does nothing.
- S11: the test now reads the tick error's `stack` and `causes`; confirm the Dagster GraphQL `PythonError` has those fields and that "Ingest failed" is in them.
- `FNCLI_ADMIN_USER`: the first Keycloak user's backend login name (probably its email). Not checked.
- How a duplicate `merge_commit_sha` under a new PR number surfaces to the caller (ADR 0023 says not checked), and whether the Dagster sensors handle a 409 on an already finished task (ADR 0026).
- Whether a test cross-checks the Dagster enums against the webserver's (ADR 0026 says it found none).
- CI: `build.yml` does not trigger for PRs into `split/*`; use `workflow_dispatch` or retarget when the route into `dagster-develop` is chosen. The route itself is undecided.

## Docs still stale

- `project/handover/moonshot-as-built.md` still describes backfill, `IGNORED` and the drain rules; the decision records are the source of truth.
- The Hypothesis rule set (`webserver/tests/test_stateful_rules.py`) was updated by the laptop controller for soft delete; its docstring is the place to check the model against ADR 0025.

## Housekeeping that needs the laptop

- Delete the redundant remote branches (`moonshot/shared-resources-routes`, `-tests`, `fncli-e2e`, `gitea-mirror-fixes`, `adr-0019-decisions`, `build-plan`, `stage-0-contracts`, `dagster-sensors`, `e2e-failure-suite`, `task-config-pinning`) and push the tag `shared-resources-tests-full` at `ee653cd2`. The cloud proxy refuses ref deletion and tags.
- Beta items this work does not touch: #536 (isolation, NetworkPolicy, RBAC, per-task secrets), #537 beyond the launcher, #538, #539, #500.
