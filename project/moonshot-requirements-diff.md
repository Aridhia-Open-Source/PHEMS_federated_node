# Requirements vs code: what does not match

> **Status at end of day 2026-10-17. Read this first: the sections below predate some of it.**
> - **Proven live:** the happy path passed end to end on kind-fn (Gitea PR → `YIELDED` → task `SUCCESS` → results PR `OPENED` → `MERGED`), by hand and as the automated test.
> - **GitProvider:** global `GitProvider` (`/global/providers`: `name`, `type` github|gitea, `uri` unique, `api_uri`, `enabled`).
>   - Trigger and results repos are `provider_id` + `repo_path` + `secret_id` (token per repo, for least privilege) + `enabled`, unique `(provider_id, repo_path)`; the `uri` is derived.
>   - A disabled provider makes its repos inactive.
>   - Migration 002. No `upstream_id` yet.
> - **Routes:**
>   - tasks under `/projects/:pid/tasks/...`, plus `GET .../tasks/:id/trigger`
>   - `service-info` deleted
>   - `/global/users`, `/global/registries`, `/global/whitelisted_images`
>   - results under `/projects/:pid/results`
> - **Integrity and locking:**
>   - PRs unique by `(repo, merge_commit_sha)` as well as number (baseline migration)
>   - new projects start **locked** (baseline migration); fncli `setup-project` unlocks at the end, and teardown locks before deleting
> - **Sensors:** one interval for all sensors, `fnDagster.sensors.minIntervalSeconds` (30s default, 2s in dev; PR #554, merged).
> - **Tooling:**
>   - fncli moved into `dagster/fncli` and shares `app.*`; install with `pipx install --force --editable './dagster[cli]'`
>   - Dagster and fncli unit tests run in Docker (`dagster/run_tests.sh`)
>   - e2e: `pytest dagster --e2e [success|failure] -v` from the repo root. The suites are granular (each fncli command and state change is its own test). The failure suite has never been run.
> - **Not built yet:** auth (planned in `project/auth-mvp-plan.md`).
> - **gitea-mirror is parked for the beta.** Post-beta it becomes a stateless mirror service with number-matched PR replay, which the node sees as a `gitea` GitProvider.
> - **To do:** a full refresh of this document, and a narrow bug review (the baseline migration, lock/drain rules, sensors). See `.claude/handover.md`.


- Compared: `moonshot-requirements.md` (72 IDs) against `moonshot-as-built.md`.
- Code: `moonshot/shared-resources` @ 95d61117 (local) and `origin/moonshot/gitea-mirror` @ 3b551cb7.
- Every row below was re-checked in the code. Nothing was run. Test counts are as reported.

## Counts

| Match | Differs | Missing in code | Not in requirements | Untested |
|---|---|---|---|---|
| 60 | 11 | 1 | 24 (the ones listed below) | 8 (overlaps the others) |

Match + Differs + Missing = 72. "Untested" is a flag, not a separate bucket.

## Verdict for the beta

- The shared-resources code does what the requirements say, apart from 11 small gaps. None of them blocks the beta.
- The biggest risk is not a code gap. The end-to-end script has never run on a real cluster.
- The mirror is built and unit-tested but is not part of the beta flow (the node-side receiver is not built, GM-19). It also cannot be merged as-is: its fncli commands use code that no longer exists.
- Four known ingest and trigger-loss bugs (B1 to B5 below) are still in the code. They are rare. Owner decides if any block the beta.

## Differs

| ID and title | Requirement says | Code does | Q | MVP blocker? |
|---|---|---|---|---|
| SR-GLOB-01 Resources created only under /global | Admin creates global resources. ADR: admin role | `PATCH /global/secrets/<label>` needs only `can_admin_dataset` (`webserver/app/secrets_api.py:38-40`, no admin check at `:182`) | Q1 | no. Rotation by a dataset admin is acceptable for the MVP |
| SR-PR-04 Trigger states | REJECTED is final | PATCH can move a REJECTED trigger to UNKNOWN or YIELDED. `Trigger.set_state` has no current-state check (`webserver/app/models/trigger.py:71-85`). A test asserts it (`test_pull_requests_and_tasks.py:305-314`) | none | no. Only the admin and Dagster call this PATCH |
| SR-SENS-06 New 409s are skipped | A 400 or 500 in those places still raises | In evaluate, a 400 from `POST .../task` is logged and not raised (`dagster/app/definitions/sensors/git/evaluate_job.py:43-47`). Only other codes raise | none | no. The webserver already marked the PR REJECTED |
| SR-SENS-09 Only run-status sensors write task status | Only the 5 run-status sensors write status | The launcher also PATCHes FAILED when a dataset is unusable (`launcher.py:52-54`). Retry sets PENDING (`tasks_api.py:202`). SR-SENS-08 already says the launcher does this | none | no. The requirement contradicts itself |
| SR-API-01 Admin routes under /global | `/whitelisted_images` lives under `/global` | Blueprint has the prefix but is not registered (`webserver/app/__init__.py:84-87`). `GET /audit` and `PATCH /delivery-secret` stay at the root | Q17 | no. Legacy models are parked |
| SR-API-02 Consistent lists | Lists paginate consistently; page or per_page 0 gives 1 | Not uniform. Task list key is `tasks`, link lists and global repo and secret lists are bare arrays, others use `items` (`tasks_api.py:94-116`, `secrets_api.py:126`). Project PR list passes `page` and `per_page` straight to the paginator (`project_trigger_repositories_api.py:248-266`). Unverified: what it returns for 0 | Q2 | no |
| SR-API-03 Real model, no flat layer | No stale routes | `openapi.json` still lists `/task_requests*` and `/global/whitelisted_images*`. The routes are not served. No `/tasks` root, `IGNORED` or `service-info` there | Q18 | no. Docs only |
| GM-07 Shadow users | Author named after the GitHub login | Named `gh-<login>` (`gitea-mirror/app/gitea.py:14-39`). Follows the README, not the ADR text | Q24 | no |
| GM-09 Webhooks | A disabled webhook receives nothing | New events skip it. A delivery already queued is still sent, `attempt_delivery` does not check `enabled` (`app/delivery.py:425-436`) | none | no |
| GM-15 Health | DB down, dead thread or stale tick gives 503 | DB failure gives 500. 503 only for a dead or stale sync loop (`app/main.py:9-22`) | none | no |
| GM-18 Mirror tests | `./run_gitea_tests.sh` passes (365) | Default target is only `tests/test_gitea_client.py` (`run_gitea_tests.sh:4`). CI skips `test_sync_robust_gitea.py` (`.github/workflows/build.yml`, mirror branch). Counts unverified | Q29 | no |

## Missing in code

| ID and title | Requirement says | Code does | Q | MVP blocker? |
|---|---|---|---|---|
| GM-17 fncli mirror commands | `fncli mirror ...` exists (target: `dagster/fncli`) | Only on the mirror branch, under `scripts/fncli/cmds/mirror.py`. It imports `fncli.dagster.utils` and `fncli.dagster.config`, deleted by the move. Needs a port to `app.*` | Q28 | no. The mirror is not in the beta flow. Yes if the beta must drive the mirror with fncli |

## Untested

| ID and title | Not covered | Q | MVP blocker? |
|---|---|---|---|
| SR-DEV-06 End-to-end script | The script has never run on a cluster (`scripts/e2e_shared_resources.sh:12`). Only in-process tests (`test_e2e_flow.py`) and the `e2e_check.py` reader are tested | Q21 | unsure. A real run is the only proof the whole flow works |
| GM-16 Deployment | Helm unit tests exist. Nothing on a real cluster. CI use of helm unittest not checked | Q27 | no for the node beta. Yes if the beta ships the mirror |
| SR-TASK-02 service-info deleted | No test asserts the 404. Route is gone, `openapi.json` is clean | none | no |
| SR-DEV-04 Baseline migration | No test runs upgrade, downgrade, upgrade. The state-cause check is tested in `test_triggers.py` | none | no |
| SR-DEV-05 Dev cluster guard | Shell scripts, no test | none | no |
| GM-01 Self-contained | No direct test. Import scan was clean | Q22 | no |
| GM-03 Rebase merges | Never found upstream, untested | Q23 | no |
| SR-SENS-07 Disabled secret | Delivery and launcher cases are tested. `test_secrets.py` and `test_git_api_factory.py` have no disabled case | none | no |

## Known bugs from review (still in code)

| Bug | Status | MVP blocker? |
|---|---|---|
| B1 duplicate path in one PR 500s the batch | Verified. Comment still at `dagster/app/definitions/sensors/git/pr_ingest.py:67`, nothing de-duplicates | no. GitHub does not repeat a path in one PR |
| B2 fan-out racing a backfill can lose a trigger | Verified. No lock in `pull_request_fanout.py` | unsure. Rare, needs a link change during an ingest |
| B3 same-second merge lost at the cursor | Verified. Polls use `merged_at >` (`dagster/app/github.py:58`, `gitea.py:56`) | unsure. A PR merged in the same second as the newest stored one |
| B4 stale global cursor replays a gap | Unverified | unsure |
| B5 empty file list matches nothing for good | Verified. Truncation is only set at 3000 files (`dagster/app/models/pull_request.py:49`) | no. A provider returns files for a merged PR |

## Built but not in requirements

Shared-resources:

- Project `PATCH`: only `enabled` and `locked`. Changing `enabled` needs locked and drained.
- `in_flight_task_ids` counts PENDING, QUEUED, RUNNING, SUCCESS with no result, and results IN_PROGRESS.
- Task creation is refused (409) on a locked project. Evaluate skips locked projects. The launcher and ingest do not.
- Fan-out ignores project `enabled` and `locked`.
- `/dagster/sensors` admin routes: list, get, start and stop sensors through Dagster GraphQL.
- `PATCH /delivery-secret` and the task routes `cancel`, `logs`, `results/approve`, `results/block` return 501.
- API tasks (`POST /projects/:pid/tasks`) as a second trigger kind (`ApiRequestTrigger`).
- Task spec: 64 KiB cap on `spec_raw`, env key rules, `catalogue` and `dictionaries` on datasets.
- Repository URI is normalised (lowercase, no `.git`). `api_uri` must be on the repository's own host.
- Results delivery: 10 MiB zip cap, token sent by header env, 60 s git timeout, committer `phems-bot`.
- Results sync also finds the PR of a PUSHED result by branch. A PR deleted on the provider is skipped.
- Project healthcheck reports `error` when the project has no trigger link.
- The webserver's own `get_token` does not check `secret.enabled`. Healthcheck still reads a disabled secret.
- All sensors start STOPPED unless `DAGSTER_SENSORS_INITIAL_STATUS` says otherwise.
- fncli ships in the Dagster image.

Gitea-mirror:

- `POST /webhooks/<id>/test` and `GET /webhooks/<id>/deliveries`.
- `requeue_failed` helper, no route and no command.
- Poison-PR quarantine: a failing PR gets no row and is retried every round.
- Branch collision guard: an upstream branch named `pr` or `pr/<n>` fails the sync.
- Per-mirror git cache in an `emptyDir`.
- Rate-limit pause per mirror, ETag reuse, 3 retries on GitHub 5xx.
- Duplicate ping and timer code in `sync.py` and `webhooks.py`. Only the runner versions run.
- Mirror create defaults `enabled=True` but the column default is false.
- Gitea init job also creates the mirror's access token secret.
