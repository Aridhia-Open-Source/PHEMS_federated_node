# 0020. Gitea mirror service: a self-contained GitHub mirror with generic webhooks

- Status: Proposed (not built; gated on a Gitea spike). Build plan: [gitea-mirror-plan.md](../handover/gitea-mirror-plan.md).
- Replaces the parked mirror design in [0018](0018-global-resources-and-gitea-mirror.md).
- Revised 2026-10-16: the service has its own database and API and no ConfigMap; webhooks are generic subscriptions rather than a call to the webserver. It no longer depends on [0019](0019-global-resources-and-shared-pull-requests.md); the node's webhook receiver does.

## Context

The sensors poll GitHub directly ([0006](0006-github-ingest-pulls-endpoint.md)). That puts GitHub tokens and rate limits in the evaluation path, polls once per project, and reads PR files and spec contents from GitHub. A mirror in the node's own Gitea lets the evaluation path read locally. The node stays outbound-only: nothing inbound is exposed to the internet.

The sensors already support Gitea ([0005](0005-git-api-protocol-and-factory.md)). Real-time delivery is not a requirement.

## Decision

A separate service with **zero knowledge of the federated node**: no webserver calls, no shared schema, no Dagster. It runs in the cluster beside Gitea. The node uses a mirror by registering the Gitea repository as an ordinary trigger repository and, optionally, by subscribing its own endpoint to the service's webhooks.

### What it does

- Outbound only. It polls GitHub (conditional requests, an `updated_at` cursor) and fetches branches and `refs/pull/*/head`.
- It pushes to a normal Gitea repository, not a Gitea pull mirror, which is expected to be unable to hold pull requests (verify).
- Scope is merged pull requests into the base branch. Per PR it creates a `pr/<n>` branch, opens a Gitea pull request, and marks it merged with `manually-merged` at GitHub's `merge_commit_sha`. No comments, reviews or open pull requests.
- Sync always starts from the current time: creating a mirror sets the cursor to now. There is no history backfill of pull requests; branches are pushed in full.
- Authors are shadow Gitea users named after the GitHub login, acted as through the admin `Sudo` header, so `raised_by` matches upstream. Shadow users are preloaded from the upstream repository's contributors and collaborators when a mirror is created, and created on demand for anyone missing.
- A pull request row is recorded before the cursor advances, and `unique(mirror_id, number)` makes a repeat after a crash harmless.

### Webhooks

Generic subscriptions: anyone registers an endpoint; the service knows nothing about who is listening.

- `webhooks` table: endpoint URL, a reference to the secret holding the HMAC key, an optional filter on mirrors, enabled.
- After a PR is pushed to Gitea (so the merge commit is readable), the service POSTs an event to each matching endpoint: `event` (`pull_request.mirrored`), `mirror` (upstream URI, Gitea owner and repository), `number`, `title`, `author`, `merged_at`, `merge_commit_sha`.
- Signed with an HMAC over the body; a delivery id header lets receivers drop duplicates.
- Delivered from an outbox (`webhook_deliveries`) with retry and backoff; deliveries are at-least-once, so receivers must be idempotent.
- The event is defined by a written JSON schema in the service; receivers test against it and do not import service code.

The node's receiver (a later, node-side change) maps the event to its trigger repository by Gitea URI and uses the same upsert and fan-out as the batch ingest endpoint ([0019](0019-global-resources-and-shared-pull-requests.md) sections 3 and 4). `unique(trigger_repository_id, number)` makes duplicates harmless. Sensor polling of the Gitea repository stays as the backstop for a missed event.

### State and configuration

- Its own database, `gitea_mirror`, on the shared Postgres server, with its own user and secret, created by the chart's database init job.
- Tables: `mirrors` (upstream URI, GitHub token secret reference, Gitea owner and repository, base branch, enabled), `mirror_state` (cursor, last sync, last error), `mirrored_pull_requests`, `webhooks`, `webhook_deliveries`.
- Mirrors and webhooks are managed through the service's own cluster-only API (create, list, status, resync, refresh users, register and test webhooks), called by `fncli` or an operator. No ConfigMap.
- The GitHub token is read from Kubernetes by reference and passed to git through an HTTP header, never the remote URL.

## Needed alongside it

- Cluster: a deployment; a service account with `get` on only the secrets it needs; a network policy with egress to GitHub, Gitea, Postgres and registered webhook endpoints; a Gitea admin token (from the existing admin init job) for orgs, repositories and shadow users.
- Operations: `fncli mirror` commands; health and status per mirror (last sync, expired token).
- Tests: integration tests against a real Gitea in Docker with recorded GitHub responses.
- Node side, later: the webhook receiver (needs 0019 stages 1 to 5 for the shared upsert and fan-out), and `mirror_uri` and `mirror_secret_id` on global `trigger_repositories` so a repository can switch between GitHub and its mirror. Until then, register the Gitea repository directly and let the sensors poll it.

## Consequences

- The evaluation path no longer needs GitHub tokens or rate limits, and GitHub is polled once per repository however many projects use it.
- New pull requests reach a subscribed node right after a mirror sync; without a subscription, on the sensors' next Gitea poll.
- The ingest sensor can shrink to a backstop once the node subscribes.
- Results delivery and results PR sync still use GitHub, since those PRs live there.
- The service owns its own database, an outbox, and a cross-namespace secrets grant.

## Open items

Gate on a spike before building. Behaviours of Gitea to verify:

- the pull request files endpoint on a `manually-merged` PR (no-go if it fails: the sensors need it)
- `manually-merged` with squash and rebase merges
- `merged_at` being the sync time rather than GitHub's
- whether a Gitea pull mirror can hold PRs at all (assumed not), and whether `refs/pull/*` clash with Gitea's own PR refs

Also open: who creates the Gitea org and the node's read token, and one GitHub token per mirror or per org.

## Alternatives considered

- **A webhook hard-wired to the webserver** (the first version of this ADR): couples the service to the node. Generic subscriptions keep the same delivery without that knowledge.
- **Gitea's own push webhooks**: Gitea mirrors do not carry PR facts; the service already knows them from GitHub.
- **Config in a ConfigMap**: needs a redeploy to add a mirror; rows in the service's own database are managed through its API.
- **Config in Gitea's own models** (pull mirror settings, repository topics): depends on pull mirrors holding PRs, and Gitea does not return stored credentials.
- **A per-project mirror** (a Gitea org per project): duplicate mirrors and secrets.
- **Real-time GitHub webhooks into the node**: rejected, they need an inbound route.
- **Argo CD**: it syncs git refs and sees no pull request objects.
