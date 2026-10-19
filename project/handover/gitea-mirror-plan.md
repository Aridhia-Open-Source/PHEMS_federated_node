# Gitea mirror: design and build plan

The mirror is not built, so it is described here and not in the decision records. This is its design (context, decisions, open items, rejected alternatives) followed by the build plan.

## Context

The sensors poll GitHub directly. That puts GitHub tokens and rate limits in the evaluation path, polls once per repository, and reads pull request files and spec contents from GitHub. A mirror in the node's own Gitea would let the evaluation path read locally. The node stays outbound-only: nothing inbound is exposed to the internet. The sensors already support Gitea ([ADR 0010](../decisions/0010-git-api-protocol-and-factory.md)). Real-time delivery is not a requirement.

## Design decisions

- A separate service with **zero knowledge of the federated node**: no webserver calls, no shared schema, no Dagster. It runs in the cluster beside Gitea.
- Outbound only. It polls GitHub (conditional requests, an `updated_at` cursor) and fetches branches and `refs/pull/*/head`.
- It pushes to a normal Gitea repository, not a Gitea pull mirror, which is expected to be unable to hold pull requests (to verify).
- Scope is merged pull requests into the base branch. Per pull request it creates a `pr/<n>` branch, opens a Gitea pull request, and marks it merged with `manually-merged` at GitHub's `merge_commit_sha`. No comments, reviews or open pull requests.
- Sync always starts from the current time: creating a mirror sets the cursor to now. There is no history backfill of pull requests; branches are pushed in full.
- Authors are shadow Gitea users named after the GitHub login, acted as through the admin `Sudo` header, so `raised_by` matches upstream.
- A pull request row is recorded before the cursor advances, and `unique(mirror_id, number)` makes a repeat after a crash harmless.
- **Webhooks are generic subscriptions:** anyone registers an endpoint; the service knows nothing about who is listening. After a pull request is pushed to Gitea, the service POSTs `pull_request.mirrored` to each matching endpoint, signed with an HMAC, from an outbox with retry and backoff (at-least-once, so receivers must be idempotent). The event is defined by a written JSON schema.
- The node's receiver (a later, node-side change) maps the event to its trigger repository by Gitea URI and uses the same upsert and fan-out as the batch ingest endpoint ([ADR 0011](../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md)). Sensor polling of the Gitea repository stays as the backstop for a missed event.
- The service has its own database (`gitea_mirror`) and its own cluster-only API; no ConfigMap. The GitHub token is read from Kubernetes by reference and passed to git through an HTTP header, never the remote URL.
- Needed alongside it: a deployment; a service account with `get` on only the secrets it needs; a network policy with egress to GitHub, Gitea, Postgres and registered webhook endpoints; a Gitea admin token for orgs, repositories and shadow users; `fncli mirror` commands; integration tests against a real Gitea in Docker.

### Consequences once built

- The evaluation path no longer needs GitHub tokens or rate limits, and GitHub is polled once per repository however many projects use it.
- New pull requests reach a subscribed node right after a mirror sync; without a subscription, on the sensors' next Gitea poll. The ingest sensor can shrink to a backstop.
- Results delivery and results pull request sync still use GitHub, since those pull requests live there.
- The service owns its own database, an outbox, and a cross-namespace secrets grant.

### Rejected alternatives

- A webhook hard-wired to the webserver: couples the service to the node.
- Gitea's own push webhooks: Gitea mirrors do not carry pull request facts.
- Config in a ConfigMap (needs a redeploy to add a mirror) or in Gitea's own models (depends on pull mirrors holding pull requests; Gitea does not return stored credentials).
- A per-project mirror (a Gitea org per project): duplicate mirrors and secrets.
- Real-time GitHub webhooks into the node: they need an inbound route.
- Argo CD: it syncs git refs and sees no pull request objects.

### Open items (gate on a spike before building)

- The pull request files endpoint on a `manually-merged` pull request (no-go if it fails: the sensors need it).
- `manually-merged` with squash and rebase merges.
- `merged_at` being the sync time rather than GitHub's.
- Whether a Gitea pull mirror can hold pull requests at all (assumed not), and whether `refs/pull/*` clash with Gitea's own pull request refs.
- Who creates the Gitea org and the node's read token, and one GitHub token per mirror or per org.

## Build plan

## What it is

A self-contained service that mirrors GitHub repositories into the node's Gitea, merged pull requests included, over outbound-only connections.

- **Zero knowledge of the federated node.** No webserver calls, no shared schema, no Dagster.
- The node uses a mirror by registering the Gitea repository as an ordinary trigger repository (the sensors already speak Gitea, ADR 0010), and can subscribe its own endpoint to the service's generic webhooks.
- **Not blocked by the global resource model (ADR 0006).** The node-side receiver and `mirror_uri` are separate, later changes.

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
| `webhooks` | • `id`, `url`<br>• `secret_namespace`, `secret_key` (HMAC key)<br>• `mirror_id` (nullable: null means all mirrors)<br>• `enabled` |
| `webhook_deliveries` | • `id` (sent as the delivery id), `webhook_id`, `mirrored_pull_request_id`<br>• `status` (pending, delivered, failed), `attempts`, `next_attempt_at`, `last_error` |

## API (service-internal, cluster-only)

- `GET/POST /mirrors`, `GET/PATCH/DELETE /mirrors/<id>`
- `GET /mirrors/<id>/status`: last sync, last error, PRs mirrored, an expired-token flag
- `POST /mirrors/<id>/resync`: run a sync now
- `POST /mirrors/<id>/users/sync`: preload or refresh shadow users
- `GET/POST /webhooks`, `GET/PATCH/DELETE /webhooks/<id>`
- `POST /webhooks/<id>/test`: send a signed ping
- `GET /webhooks/<id>/deliveries`: recent deliveries and failures
- `GET /health`
- Auth: a static bearer token from a secret. Only `fncli` or an operator calls it.

## Sync loop (per enabled mirror, every N minutes)

Sync always starts from the current time: creating a mirror sets `cursor` to now, so there is no history backfill. Branches are pushed in full; only pull requests are forward-only.

1. Ask GitHub for closed PRs into `base_branch` updated since `cursor`, using conditional requests (ETag) so unchanged pages cost no rate limit.
2. Keep the merged ones that are not yet in `mirrored_pull_requests`.
3. `git fetch` the branches plus `refs/pull/<n>/head`, then `git push` them to Gitea: branches as-is, each PR head as `pr/<n>`.
4. Per PR: look up the author's shadow user (preloaded, or created now if missing), open a Gitea PR as them (`Sudo`), then mark it `manually-merged` at `merge_commit_sha`.
5. Insert the `mirrored_pull_requests` row and one `webhook_deliveries` row per matching webhook in the same transaction, then advance `cursor`, so a crash only causes a repeat that the uniqueness check skips.

## Webhook delivery (separate loop)

- Picks pending deliveries due now, POSTs the event, and marks them delivered on a 2xx response.
- Otherwise it retries with backoff, and after N attempts marks the delivery failed (visible in the API).
- Event body: `event` (`pull_request.mirrored`), `delivery_id`, `mirror` (upstream URI, Gitea owner and repository), `number`, `title`, `author`, `merged_at`, `merge_commit_sha`.
- Headers: an HMAC-SHA256 signature of the body, and the delivery id.
- The schema is written as `gitea-mirror/schema/pull_request.mirrored.json`; receivers test against it.

## Stages

| Stage | Work | Model |
|---|---|---|
| 0. Spike | • Real Gitea in Docker, done by hand or as a script<br>• Does the files endpoint work on a `manually-merged` PR?<br>• Does `manually-merged` work for squash and rebase merges?<br>• Is `merged_at` GitHub's time or the sync time?<br>• Normal repository vs pull mirror: do `refs/pull/*` clash with Gitea's own PR refs?<br>• **Go/no-go:** if the files endpoint fails, the sensors can't use the mirror | Sonnet |
| 1. Skeleton | • `gitea-mirror/` app, config, Alembic baseline for the 3 tables<br>• `/health`, Dockerfile, test runner (Postgres in Docker, as `run_tests.sh`) | Haiku |
| 2. Mirrors API | • CRUD, status, resync and user preload endpoints, bearer auth, tests | Sonnet |
| 3. GitHub client | • Merged PRs since the cursor, ETag caching, rate-limit backoff<br>• Tests with recorded responses | Sonnet |
| 4. Gitea client | • Org and repository creation, shadow users, open PR, `manually-merged`<br>• Tests against real Gitea in Docker | Sonnet |
| 5b. Webhooks | • Webhook CRUD, test ping, delivery loop, HMAC signing, event JSON schema<br>• Tests with a local receiver: signature, retry, failure after N attempts | Sonnet |
| 5. Sync engine | • Fetch and push, PR replication, cursor and idempotency rules<br>• Error recording; expired token gives a clear status, not a crash loop<br>• Integration test: recorded GitHub plus real Gitea, run twice, second run is a no-op | Opus if the spike shows surprises, otherwise Sonnet |
| 6. Chart | • Subchart or templates behind `giteaMirror.enabled`<br>• Database init entry, deployment, service, service account with `get` on named secrets only<br>• NetworkPolicy: egress to GitHub, Gitea, Postgres and in-cluster webhook receivers; ingress only from the namespace<br>• helm unittest | Sonnet |
| 7. CI | • Build and push the image in `build.yml`, using the same tag rules<br>• Run its tests | Haiku |
| 8. fncli + docs | • `fncli mirror add/list/status/resync`, calling the service API<br>• README, a short README | Haiku |

Stages 2–4 can run in parallel once stage 1 lands. Stage 5 needs 3 and 4; 5b needs 2 and the delivery rows from 5.

## Hooking the node up (later, separate)

- Smallest version: register the Gitea repository as a trigger repository with a Gitea read token. No schema change; sensors poll it.
- Webhook receiver (needs the shared upsert and fan-out, ADR 0011): an HMAC-verified endpoint that maps the event to the trigger repository by Gitea URI and reuses the batch ingest's upsert and fan-out. Register it with the mirror service's `POST /webhooks`.
- Nicer version (on the global model, ADR 0006): `mirror_uri` and `mirror_secret_id` on `trigger_repositories`, so a repository can switch between GitHub and its mirror.

## Open

- Who creates the Gitea org and the read token for the node's sensors: the service on `POST /mirrors`, or an operator.
- One GitHub token per mirror, or one shared per org.
- Sync interval default; whether results PRs ever mirror (no: results stay on GitHub).
