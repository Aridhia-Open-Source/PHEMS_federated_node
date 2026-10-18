# Review guide: the moonshot stack (PRs #555 to #561)

For a reviewer who has already been through `dagster-develop`. The work is `moonshot/shared-resources` at `c55984fb`, split by path into seven stacked draft PRs. Read bottom-up; read the decision record first in each layer, then check the code against it.

## How the stack works

- `split/00-base` is `dagster-develop` with every test file removed. It has no PR. PR 1 targets it, and each later PR targets the one below, so each diff shows only that layer.
- The top of the stack (`split/07-tests`, #561) has the same code as `moonshot/shared-resources` `c55984fb`, plus the new decision records and docs. **Lower PRs are not expected to pass CI on their own** (the tests arrive in #561). Merge the whole stack together, or merge the top.
- CI does not run on these PRs (`build.yml` only triggers for `main`, `develop`, `dagster-main` and `dagster-develop`). Test results below are from runs by hand.
- Decision records link to each other; a link to a record that arrives in a higher PR works once the stack is read to the top.

## Test status at the tip (run by hand, 2026-10-18)

| Suite | Result |
|---|---|
| Webserver, full (with the quick Hypothesis run) | 812 passed, 1 skipped, 0 failed |
| Webserver, deep Hypothesis search (`STATEFUL_DEEP=1`) | passed (about 5.6 minutes) |
| Dagster app tests | 377 passed |
| fncli unit tests | 139 passed (218 e2e tests skip without `--e2e`) |
| e2e, success suite (live, `kind-fn`) | 53 passed, 1 failed (`started_at`); see `project/handover/e2e-results-2026-10-18.md` on branch `moonshot/e2e-results-2026-10-18` |
| e2e, failure suite | partly run (107 passed, 2 failed, 31 not run); fixes for the failures are on branch `moonshot/e2e-run1-fixes` (not in this stack) |

## The layers

| PR | Layer | Records to read | Start with | Challenge |
|---|---|---|---|---|
| [#555](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/555) | Schema, models, state tables, soft delete (+1,358 / -505) | [0022](../decisions/0022-git-provider-and-repository-identity.md), [0026](../decisions/0026-state-transition-tables.md) | `migrations/versions/001_baseline.py`, `models/`, `helpers/state_rules.py`, `helpers/soft_delete.py` | Constraints and partial unique indexes; `ondelete`; the `locked` default; are the transition tables complete; does anything read a soft-deleted row it should not |
| [#556](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/556) | Webserver rules, routes, DTOs (+3,242 / -1,008) | [0021](../decisions/0021-global-resources-and-project-links.md), [0023](../decisions/0023-pull-requests-stored-once-fan-out-and-cursors.md), [0024](../decisions/0024-task-configuration-pinning.md), [0025](../decisions/0025-switching-off-revoking-and-soft-delete.md) | `helpers/pull_request_fanout.py`, `helpers/task_config.py`, `results_api.py`, `projects_api.py`, `trigger_repositories_api.py`, `project_trigger_repositories_api.py` | Can a project see another's data through a shared resource; the order of checks in `POST /results`; what `skip_gap` skips; what the snapshot leaves out |
| [#557](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/557) | Dagster ops, sensors, delivery, pypipes (+1,122 / -657) | [0027](../decisions/0027-dagster-pipeline-ops-sensors-and-retries.md), [0017](../decisions/0017-task-status-written-by-run-status-sensors.md) | `definitions/sensors/git/ingest_job.py`, `sensors/task/launcher.py`, `delivery/results.py`, `backend.py` | What happens on a 404 or 409 from the webserver; retry bounds; one failing item stopping others |
| [#558](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/558) | Helm chart, build, generated OpenAPI (+6,616 / -3,312) | 0027 (settings) | `values.yaml` (`fnDagster.sensors`), `values.schema.json`; check `openapi.json` against the routes, do not read it | Defaults (30 s, 60 s, 5 attempts); no NetworkPolicy or RBAC change (still open, #536) |
| [#559](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/559) | fncli, simulation, e2e scripts (+1,827 / -1,852) | [0015](../decisions/0015-fncli-dev-ops-tool.md), [0028](../decisions/0028-who-owns-what-webserver-record-and-dagster-history.md) | `cmds/state.py`, `cmds/simulate.py` | Dev tooling only; nothing runs in production |
| [#560](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/560) | Decision records, docs, handovers (+4,805 / -95) | [0019](../decisions/0019-global-resources-and-shared-pull-requests.md) (the umbrella) and [0028](../decisions/0028-who-owns-what-webserver-record-and-dagster-history.md) | `project/decisions/` | Do the records say what the code does; the "Not built or open" section of each |
| [#561](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/561) | Tests (+17,749) | none | skim for gaps, not line by line | Do the tests check the rules in the records, or only the code's current behaviour |

## The design decisions

One record per major change from `dagster-develop`; [0019](../decisions/0019-global-resources-and-shared-pull-requests.md) is the umbrella and maps the old decision numbers to the new records.

1. [0021](../decisions/0021-global-resources-and-project-links.md) Global resources with a per-project link.
2. [0022](../decisions/0022-git-provider-and-repository-identity.md) `GitProvider` and the identity of a repository.
3. [0023](../decisions/0023-pull-requests-stored-once-fan-out-and-cursors.md) Pull requests stored once, fan-out, cursors, skipping the gap (no backfill).
4. [0024](../decisions/0024-task-configuration-pinning.md) A task is pinned to its configuration (replaces lock-and-drain).
5. [0025](../decisions/0025-switching-off-revoking-and-soft-delete.md) Switching off, revoking and soft delete.
6. [0026](../decisions/0026-state-transition-tables.md) State transition tables.
7. [0027](../decisions/0027-dagster-pipeline-ops-sensors-and-retries.md) The Dagster pipeline.
8. [0028](../decisions/0028-who-owns-what-webserver-record-and-dagster-history.md) Who owns what, and auth deferred.

## Findings from checking the records against the code (open, not fixed)

These came from writing the records against the code. The first three are the ones to look at.

1. **A deleted dataset link leaves its task `PENDING` for ever.** The launcher gets a 404 for a deleted link, logs it, and retries every tick. Only a revoked or switched-off link gives `FAILED`. (0025)
2. **The launcher ignores `locked`.** A locked, enabled project still launches `PENDING` tasks. Only the evaluate sensor and `POST /tasks` honour the lock. Issue #540 expects this ("work already in flight carries on"); the old ADR text said otherwise. (0025, 0027)
3. **`fncli link-set --revoked` is refused (403)**: `g.caller_is_admin` checks only the `Administrator` role, not `System`. The e2e scenarios that revoke (S6, S5b, S10) fail for that reason. Fix on branch `moonshot/e2e-run1-fixes` (an admin login for fncli); the alternative is to accept `System` in `caller_is_admin`. (0028)
4. `config_hash` is stored but nothing compares it; the check diffs the stored document. Delivery uses only the snapshot's repository id and `target_dir`; the repository, provider and secret are read live. (0024)
5. A repository or provider switched off is not polled and the batch `POST` is a 400: its pull requests are stored by the catch-up once it is back on, not while it is off. (0023, 0025)
6. A PR merged just before a switch-off and not yet ingested is also skipped on switch-on (the cursor moves to now). The exact fix is a `disabled_at` column. (0023)
7. The cross-project loop check keys on `(provider_id, repo_path)`, so the same server registered under two host names is not seen as one repository. (0021, 0022)
8. A link's `active` ignores the secret; only the `pollable` filter uses it. (0021)
9. `POST .../task` does not check the project lock, so a task can be created between the lock check and creating a results link. Worst case it fails or is not delivered. (0025)
10. Stale text: `docs/architecture/entities.md` (task order "not enforced", the result diagram's 400, `STALE`, the separate `state`) and `flows.md` ("every 10 s", the default is 30); a comment on `locked` in `models/project.py` mentions drain; the `ResultState` docstring says nothing retries `FAILED` while the retry sensor does; the 2026-10-17 handover and `moonshot-plan.md` describe backfill and `IGNORED`. (0026, 0027)
11. Retrying a task that cannot be retried is a 400, not a 409. (0026)
12. Two decisions the owner still has to confirm: dataset `PATCH` returns 200, and `GET /tasks` clamps `page` and `per_page` below 1. (0019)

## Known gaps (recorded, do not re-raise as new)

- Auth, audit and normal-user permissions are out of scope; only the super user and the Dagster system user matter now ([0028](../decisions/0028-who-owns-what-webserver-record-and-dagster-history.md)).
- Beta items not in this work: task isolation and network policy (#536), pipeline resilience beyond the launcher (#537), task attempts (#538), auth (#539), the deployment gate (#500).
- No way to kill a task or delivery already running; a revoke stops the result, not the run.
- Delivery with no results link is not handled for the MVP.
- Result `state` `FAILED` stays after `DAGSTER_DELIVERY_MAX_ATTEMPTS` with no alert.

## Reading time

About 5,300 added and 2,100 removed lines of Python outside tests and the CLI (webserver about 4,300 added, Dagster about 1,050), of which about 4,100 are logic. The records are 8 files of 60 to 85 lines.
