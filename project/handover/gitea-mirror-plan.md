# Gitea mirror: build plan

Draft, 2026-10-16. Replaces the build parts of ADR 0020. ADR 0020 needs three edits to match: drop the ConfigMap, drop the webhook to the webserver, add the service's own database.

## What it is

A self-contained service that mirrors GitHub repositories into the node's Gitea, merged pull requests included, over outbound-only connections.

- **Zero knowledge of the federated node.** No webserver calls, no shared schema, no Dagster.
- The node uses a mirror by registering the Gitea repository as an ordinary trigger repository. The sensors already speak Gitea (ADR 0005).
- **Not blocked by ADR 0019.** Hooking the node up (`mirror_uri`, or just registering the Gitea URL) is a separate, later change on the node side.

## Shape

| Part | Choice |
|---|---|
| Code | • `gitea-mirror/` at the repo root, Python (Flask + SQLAlchemy + Alembic, as the webserver)<br>• Its own image, tag line and test suite |
| Database | • A new `gitea_mirror` database on the shared Postgres server, with its own user and secret<br>• Created by `db-init-jobs.yaml`, the same pattern as `gitea-db-init` |
| Config | • Rows in its own `mirrors` table, managed through its own API; no ConfigMap |
| Git cache | • An `emptyDir` volume, fetched fresh after a restart; a PVC only if fetches prove slow |
| Users | • On `POST /mirrors`, preload shadow Gitea users from the upstream repository's contributors and collaborators<br>• Unknown authors are still created on demand during sync<br>• `POST /mirrors/<id>/users/sync` refreshes the list |
| Gitea access | • An admin token from the existing `gitea-admin-init` job, used for orgs, repositories and shadow users (`Sudo` header) |
| GitHub access | • A token per mirror, read from a Kubernetes secret by reference (`namespace`, `key`)<br>• Passed to git as an HTTP header, never in the remote URL |

## Tables

| Table | Columns |
|---|---|
| `mirrors` | • `id`, `upstream_uri` (unique)<br>• `secret_namespace`, `secret_key`<br>• `gitea_owner`, `gitea_repo` (unique together)<br>• `base_branch`, `enabled` |
| `mirror_state` | • `mirror_id` (PK)<br>• `cursor` (GitHub `updated_at`)<br>• `last_sync_at`, `last_success_at`, `last_error` |
| `mirrored_pull_requests` | • `mirror_id`, `number` (unique together)<br>• `merge_commit_sha`, `merged_at`, `author`<br>• `gitea_pr_number`, `mirrored_at` |

## API (service-internal, cluster-only)

- `GET/POST /mirrors`, `GET/PATCH/DELETE /mirrors/<id>`
- `GET /mirrors/<id>/status`: last sync, last error, PRs mirrored, an expired-token flag
- `POST /mirrors/<id>/resync`: run a sync now
- `POST /mirrors/<id>/users/sync`: preload or refresh shadow users
- `GET /health`
- Auth: a static bearer token from a secret. Only `fncli` or an operator calls it.

## Sync loop (per enabled mirror, every N minutes)

Sync always starts from the current time: creating a mirror sets `cursor` to now, so there is no history backfill. Branches are pushed in full; only pull requests are forward-only.

1. Ask GitHub for closed PRs into `base_branch` updated since `cursor`, using conditional requests (ETag) so unchanged pages cost no rate limit.
2. Keep the merged ones that are not yet in `mirrored_pull_requests`.
3. `git fetch` the branches plus `refs/pull/<n>/head`, then `git push` them to Gitea: branches as-is, each PR head as `pr/<n>`.
4. Per PR: look up the author's shadow user (preloaded, or created now if missing), open a Gitea PR as them (`Sudo`), then mark it `manually-merged` at `merge_commit_sha`.
5. Insert the `mirrored_pull_requests` row, then advance `cursor`, in that order, so a crash only causes a repeat that the uniqueness check skips.

## Stages

| Stage | Work | Model |
|---|---|---|
| 0. Spike | • Real Gitea in Docker, done by hand or as a script<br>• Does the files endpoint work on a `manually-merged` PR?<br>• Does `manually-merged` work for squash and rebase merges?<br>• Is `merged_at` GitHub's time or the sync time?<br>• Normal repository vs pull mirror: do `refs/pull/*` clash with Gitea's own PR refs?<br>• **Go/no-go:** if the files endpoint fails, the sensors can't use the mirror | Sonnet |
| 1. Skeleton | • `gitea-mirror/` app, config, Alembic baseline for the 3 tables<br>• `/health`, Dockerfile, test runner (Postgres in Docker, as `run_tests.sh`) | Haiku |
| 2. Mirrors API | • CRUD, status, resync and user preload endpoints, bearer auth, tests | Sonnet |
| 3. GitHub client | • Merged PRs since the cursor, ETag caching, rate-limit backoff<br>• Tests with recorded responses | Sonnet |
| 4. Gitea client | • Org and repository creation, shadow users, open PR, `manually-merged`<br>• Tests against real Gitea in Docker | Sonnet |
| 5. Sync engine | • Fetch and push, PR replication, cursor and idempotency rules<br>• Error recording; expired token gives a clear status, not a crash loop<br>• Integration test: recorded GitHub plus real Gitea, run twice, second run is a no-op | Opus if the spike shows surprises, otherwise Sonnet |
| 6. Chart | • Subchart or templates behind `giteaMirror.enabled`<br>• Database init entry, deployment, service, service account with `get` on named secrets only<br>• NetworkPolicy: egress to GitHub, Gitea and Postgres; ingress only from the namespace<br>• helm unittest | Sonnet |
| 7. CI | • Build and push the image in `build.yml`, using the same tag rules<br>• Run its tests | Haiku |
| 8. fncli + docs | • `fncli mirror add/list/status/resync`, calling the service API<br>• README, ADR 0020 rewrite | Haiku |

Stages 2–4 can run in parallel once stage 1 lands. Stage 5 needs 3 and 4.

## Hooking the node up (later, separate)

- Smallest version: register the Gitea repository as a trigger repository with a Gitea read token. No schema change.
- Nicer version (after ADR 0019): `mirror_uri` and `mirror_secret_id` on `trigger_repositories`, so a repository can switch between GitHub and its mirror.

## Open

- Who creates the Gitea org and the read token for the node's sensors: the service on `POST /mirrors`, or an operator.
- One GitHub token per mirror, or one shared per org.
- Sync interval default; whether results PRs ever mirror (no, per ADR 0020: results stay on GitHub).
