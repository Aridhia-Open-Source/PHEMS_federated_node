# Review guide: `moonshot/shared-resources` against `dagster-develop`

For a reviewer who has already been through `dagster-develop`. The diff against it (excluding tests and fncli) is **185 files, +16,274 / -5,467**:
about **4,800 added and 3,000 removed lines of Python**, 300 lines of migrations, and the rest `openapi.json`, docs and chart/config. Counts
were taken at `07f7f73d`. The 3,000 deletions are rewrites, so compare old with new. `dagster-develop` has not moved since this branch left it.
`develop` has 51 commits that this branch does not have; merging them is a separate job.

Not in this diff: `moonshot/e2e-failure-suite` (the `REVOKED` result step, `skip_gap`, the e2e failure suite, the simulation, the Hypothesis rule
set). Review that branch separately (see `session-handover-2026-10-17.md`).

## Skip or skim
- `webserver/app/static/openapi.json` (+6,201 / -1,855): check it matches the routes, do not read it line by line.
- Tests and `conftest.py`: read only to see what a rule is expected to do.
- The handover and moonshot status docs under `project/`: they describe the state, they are not the design.
- Route moves with no logic change (`tasks_api.py`, `users_api.py`, `registries_api.py`, `whitelisted_images_api.py`): skim.

## Reading order

1. **Intent (30 minutes).** `project/decisions/0019-global-resources-and-shared-pull-requests.md` (decisions 1 to 15, the cursor paragraph and the
   Consequences gaps), `project/decisions/0018-global-resources-and-gitea-mirror.md`, then the status block at the top of
   `project/moonshot-as-built.md`.
2. **Schema.** `webserver/migrations/versions/001_baseline.py` (edited in place, ADR 0013; the only migration).
   Check: constraints (unique `(provider_id, repo_path)`, unique PR per repo by number and by merge sha),
   `ondelete` behaviour, the `enabled` default (a new project is disabled), that each migration downgrades.
3. **Models.** `webserver/app/models/`: `git_provider.py`, `git_repository.py`, `trigger_repository.py`, `results_repository.py`,
   `project_trigger_repository.py`, `project_results_repository.py`, `pull_request.py`, `pull_request_trigger.py`, `project.py`. Check: what
   `active` means for each link (the global resource, the provider, the link's `enabled` and `revoked`).
4. **The core rules (spend the time here).**
   - `webserver/app/helpers/pull_request_fanout.py` (+176): how a stored PR becomes a trigger. Check the cursor rule, `unmatched_cause`,
     `backfill` (used when a project is enabled with `backfill: true`), and that two writers cannot create a duplicate trigger.
   - `webserver/app/helpers/project_state.py`: `require_disabled` (a results repository is linked only to a disabled project), and where
     the route calls it.
   - `webserver/app/trigger_repositories_api.py` (+139 / -309), `project_trigger_repositories_api.py` (+351), `projects_api.py` (+402 / -101):
     ingest, link create, enable and revoke, `post_task` guards (`?active=true`, 409 on an inactive link), delete and PATCH rules.
   - `webserver/app/results_api.py` and `tasks_api.py`: a finished task cannot change status; `POST /results` needs a `SUCCESS` task and an
     active link (409).
5. **Providers and DTOs.** `git_providers_api.py` (+136), `dtos/trigger_repository.py`, `dtos/git_provider.py`, `dtos/dataset.py`,
   `helpers/git_uri.py`, `dtos/repository_uri.py`: validation (400 not 500), URI normalisation, `api_uri` rules.
6. **Dagster.** `dagster/app/backend.py` (+138 / -141), `definitions/sensors/git/pr_ingest.py` (batches of 100, one failing repository does not stop
   the others), `delivery/results.py`, `models/*`, the sensors that call the backend with filters (`launcher.py`, `pr_evaluate.py`,
   `pull_request_sync.py`). Check: 409s are skipped not raised, filters are sent to the webserver, a disabled secret is refused before its token
   is read.
7. **Chart.** `k8s/federated-node/` (templates, `values.yaml`, `values.schema.json`): the sensor interval value
   (`fnDagster.sensors.minIntervalSeconds`), env config, init job.
8. **Everything else** (healthcheck, `helpers/dagster.py`, `dagster_api.py`, secrets and datasets APIs, `kubernetes_names.py`) last.

## Questions to ask while reading
- Can a project ever see another project's data, tasks or PRs through a shared resource?
- The results link route: does it call the disabled check, and is the order "check, then change" safe?
- Every place that decides "active": does it include the provider's `enabled` and the global resource's `enabled`?
- Any path that returns 500 on bad input instead of 400 or 409?
- Anything that reads a token or secret without checking it is enabled and the link is not revoked?

## Known gaps (already recorded, do not re-raise as new)
- The disabled check and the results link are two steps; `post_task` does not check the project is enabled (ADR 0019, Consequences). Accepted, post-beta.
- A revoked secret link is still used when a token is read (Dagster); revoked or disabled secrets are enforced only at create and patch.
- Delivery with no results link is not handled (comment in Dagster).
- The ingest versus link-create race, and `get_or_assign_*` in fncli returning an existing link with different settings.
- Auth, audit and normal-user permissions are out of scope (a rewrite later); only the super user and the Dagster system user matter now.
- The open beta issues (#536, #537, #539, #500) are listed in `session-handover-2026-10-17.md`.
