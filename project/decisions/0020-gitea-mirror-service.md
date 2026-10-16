# 0020. Gitea mirror service: a self-contained GitHub mirror with generic webhooks

- Status: Proposed. Built (local, unreviewed): stages m0 to m5b and m8 on local branches, nothing pushed. Spike: GO, see [SPIKE.md](../../gitea-mirror/SPIKE.md). Build plan: [gitea-mirror-plan.md](../handover/gitea-mirror-plan.md).
- Replaces the parked mirror design in [0018](0018-global-resources-and-gitea-mirror.md).
- Revised 2026-10-16: the service has its own database and API and no ConfigMap; webhooks are generic subscriptions rather than a call to the webserver. It no longer depends on [0019](0019-global-resources-and-shared-pull-requests.md); the node's webhook receiver does.

## Context

The sensors poll GitHub directly ([0006](0006-github-ingest-pulls-endpoint.md)). That puts GitHub tokens and rate limits in the evaluation path, polls once per project, and reads PR files and spec contents from GitHub. A mirror in the node's own Gitea lets the evaluation path read locally. The node stays outbound-only: nothing inbound is exposed to the internet.

The sensors already support Gitea ([0005](0005-git-api-protocol-and-factory.md)). Real-time delivery is not a requirement.

## Decision

A separate service with **zero knowledge of the federated node**: no webserver calls, no shared schema, no Dagster. It runs in the cluster beside Gitea. The node uses a mirror by registering the Gitea repository as an ordinary trigger repository and, optionally, by subscribing its own endpoint to the service's webhooks.

### What it does

- Outbound only. It polls GitHub (conditional requests, an `updated_at` cursor) and fetches branches and `refs/pull/*/head`.
- It pushes to a normal Gitea repository, not a Gitea pull mirror. The spike confirmed a pull mirror cannot hold pull requests (the PR API is 404), and its imported `refs/pull/*` clash with the ones Gitea writes for its own PRs.
- Scope is merged pull requests into the base branch. Per PR it pushes the head as a `pr/<n>` branch (a normal repository rejects pushes into `refs/pull/*`), opens a Gitea pull request, and marks it merged with `manually-merged` at GitHub's `merge_commit_sha`. The repository is created with `allow_manual_merge`. No comments, reviews or open pull requests.
- Pull requests are replayed in `merged_at` order. For each, the Gitea base branch is force-pushed to `merge_commit_sha^1`, the PR is opened, then the base is fast-forwarded to `merge_commit_sha` and the PR marked merged. Without this, the PR files endpoint returns nothing for merge-commit and fast-forward merges, because the head is already in the base. It needs a force push on the Gitea base branch (no protection) and a per-mirror lock.
- Gitea numbers pull requests itself, so its number is not GitHub's. `mirrored_pull_requests` stores both and the event carries both.
- Sync always starts from the current time: creating a mirror sets the cursor to now. There is no history backfill of pull requests; branches are pushed in full.
- Authors are shadow Gitea users named after the GitHub login, acted as through the admin `Sudo` header, so `raised_by` matches upstream. Shadow users are preloaded from the upstream repository's contributors and collaborators when a mirror is created, and created on demand for anyone missing.
- A pull request row is recorded before the cursor advances, and `unique(mirror_id, number)` makes a repeat after a crash harmless. Gitea does not refuse a second PR for the same head, so this check is the only guard.

### Webhooks

Generic subscriptions: anyone registers an endpoint; the service knows nothing about who is listening.

- `webhooks` table: endpoint URL, a reference to the secret holding the HMAC key, an optional filter on mirrors, enabled.
- After a PR is pushed to Gitea (so the merge commit is readable), the service POSTs an event to each matching endpoint: `event` (`pull_request.mirrored`), `delivery_id`, `mirror` (upstream URI, Gitea owner and repository), `number` (GitHub's), `gitea_pr_number` (the index to read `/pulls/{index}/files` with), `title`, `author`, `merged_at` (GitHub's, since Gitea's is the sync time and cannot be set), `merge_commit_sha`.
- Signed with an HMAC-SHA256 over the body (`X-Gitea-Mirror-Signature: sha256=<hex>`); `X-Gitea-Mirror-Delivery` carries the delivery id so receivers can drop duplicates. `X-Gitea-Mirror-Event` names the event, and `POST /webhooks/<id>/test` sends a signed `ping`.
- Delivered from an outbox (`webhook_deliveries`), 5 attempts with backoff from 30 seconds, doubling; deliveries are at-least-once, so receivers must be idempotent.
- The event is defined by a written JSON schema in the service (`gitea-mirror/schema/pull_request.mirrored.json`); receivers test against it and do not import service code.

The node's receiver (a later, node-side change) maps the event to its trigger repository by Gitea URI and uses the same upsert and fan-out as the batch ingest endpoint ([0019](0019-global-resources-and-shared-pull-requests.md) sections 3 and 4). `unique(trigger_repository_id, number)` makes duplicates harmless. Sensor polling of the Gitea repository stays as the backstop for a missed event.

### State and configuration

- Its own database, `gitea_mirror`, on the shared Postgres server, with its own user and secret, created by the chart's database init job.
- Tables: `mirrors` (upstream URI, GitHub token secret reference, Gitea owner and repository, base branch, enabled), `mirror_state` (cursor, last sync, last error), `mirrored_pull_requests`, `webhooks`, `webhook_deliveries`.
- Mirrors and webhooks are managed through the service's own cluster-only API (create, list, status, resync, refresh users, register and test webhooks), called by `fncli mirror` or an operator, with a bearer token. No ConfigMap. Resync runs a sync for that mirror now (200, 409 when its lock is held, 502 on upstream errors).
- The GitHub token is read from Kubernetes by reference and passed to git through an HTTP header, never the remote URL.

## Needed alongside it

- Cluster: a deployment; a service account with `get` on only the secrets it needs; a network policy with egress to GitHub, Gitea, Postgres and registered webhook endpoints; a Gitea admin token (from the existing admin init job) for orgs, repositories and shadow users.
- Operations: `fncli mirror` commands (built: add, list, status, resync, users-sync, webhook add, list, deliveries); health and status per mirror (last sync, expired token).
- Tests: integration tests against a real Gitea in Docker with recorded GitHub responses.
- Node side, later: the webhook receiver (needs 0019 stages 1 to 5 for the shared upsert and fan-out), and `mirror_uri` and `mirror_secret_id` on global `trigger_repositories` so a repository can switch between GitHub and its mirror. Until then, register the Gitea repository directly and let the sensors poll it.

## Consequences

- The evaluation path no longer needs GitHub tokens or rate limits, and GitHub is polled once per repository however many projects use it.
- New pull requests reach a subscribed node right after a mirror sync; without a subscription, on the sensors' next Gitea poll.
- The ingest sensor can shrink to a backstop once the node subscribes.
- Results delivery and results PR sync still use GitHub, since those PRs live there.
- The service owns its own database, an outbox, and a cross-namespace secrets grant.

## Spike findings

Run against Gitea 28.1.0 (the chart's tag) and a public GitHub repository. Verdict: GO, with one change to the sync loop. Details in [SPIKE.md](../../gitea-mirror/SPIKE.md).

- The PR files endpoint works on `manually-merged` PRs only if the PR is opened while the base is at `merge_commit_sha^1`. Hence the ordered replay above.
- `manually-merged` works for merge-commit, squash and fast-forward merges. It needs `allow_manual_merge` on the repository and the merge commit already on the Gitea base branch.
- `merged_at` is the sync time and cannot be set through the API, so the event carries GitHub's.
- Gitea's PR number is not GitHub's.
- A pull mirror cannot hold pull requests, so a normal repository is used.
- Shadow users need write access on a private repository to open PRs with `Sudo`.
- A rebase merge with rewritten SHAs was not found upstream and is untested. It has the same shape as squash.

## Open items


- Known gaps are listed in `gitea-mirror/README.md` (crash between opening a Gitea PR and recording it, multi-commit fast-forward file lists, no branch deletion).
- The container runs `python -m app.runner` (API plus sync timer), configured by `GITEA_MIRROR_GIT_CACHE_DIR` and `GITEA_MIRROR_SYNC_INTERVAL_SECONDS` among others.
- Who creates the Gitea org and the node's read token.
- One GitHub token per mirror or per org (built as one secret reference per mirror).
- The throwaway `base/<n>` branch alternative to the force push is untested.

## Alternatives considered

- **A webhook hard-wired to the webserver** (the first version of this ADR): couples the service to the node. Generic subscriptions keep the same delivery without that knowledge.
- **Gitea's own push webhooks**: Gitea mirrors do not carry PR facts; the service already knows them from GitHub.
- **Config in a ConfigMap**: needs a redeploy to add a mirror; rows in the service's own database are managed through its API.
- **Config in Gitea's own models** (pull mirror settings, repository topics): depends on pull mirrors holding PRs, and Gitea does not return stored credentials.
- **A per-project mirror** (a Gitea org per project): duplicate mirrors and secrets.
- **Real-time GitHub webhooks into the node**: rejected, they need an inbound route.
- **Argo CD**: it syncs git refs and sees no pull request objects.
