# 0020. Gitea mirror service: a self-contained GitHub mirror that fires webhooks at the webserver

- Status: Proposed (not built; depends on [0019](0019-global-resources-and-shared-pull-requests.md); gated on a Gitea spike)
- Replaces the parked mirror design in [0018](0018-global-resources-and-gitea-mirror.md).

## Context

The sensors poll GitHub directly ([0006](0006-github-ingest-pulls-endpoint.md)). That puts GitHub tokens and rate limits in the evaluation path, polls once per project, and reads PR files and spec contents from GitHub. A mirror in the node's own Gitea lets the evaluation path read locally. The node stays outbound-only: nothing inbound is exposed to the internet.

The sensors already support Gitea ([0005](0005-git-api-protocol-and-factory.md)). Real-time delivery is not a requirement.

## Decision

A separate service, with no dependency on the webserver, Dagster or the database. It runs in the cluster beside Gitea.

### What it does

- Outbound only. It polls GitHub (conditional requests, an `updated_at` cursor) and fetches branches and `refs/pull/*/head`.
- It pushes to a normal Gitea repository, not a Gitea pull mirror, which is expected to be unable to hold pull requests (verify).
- Scope is merged pull requests into the base branch. Per PR it creates a `pr/<n>` branch, opens a Gitea pull request, and marks it merged with `manually-merged` at GitHub's `merge_commit_sha`. No comments, reviews or open pull requests.
- Authors are shadow Gitea users named after the GitHub login, acted as through the admin `Sudo` header, so `raised_by` matches upstream.
- The git push finishes before the webhook fires, so the merge commit is readable by the time the webserver acts on it.

### How it talks to the webserver

After a PR is mirrored it POSTs a small normalized event to a webserver endpoint: repository, `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`.

- Signed with an HMAC over a shared secret; the webserver verifies it.
- Idempotent: `unique(trigger_repository_id, number)` makes duplicates harmless.
- The service retries with backoff and records what it has sent. A missed event is repaired by the next sync, and a slow reconcile poll is the backstop.
- The event is defined by a written JSON schema both sides test against. The service does not import webserver code.
- The webserver maps the event to its global `trigger_repositories` row, stores the PR in `pull_requests` and fans out to projects, using the same upsert-plus-fan-out logic as the batch ingest endpoint ([0019](0019-global-resources-and-shared-pull-requests.md) sections 3 and 4). It needs 0019 stages 1 to 5 (global trigger repositories, `pull_requests`, fan-out and backfill) before it can be built.

### Configuration

The service reads a config file (a ConfigMap): for each repository its upstream URI, a reference to the Kubernetes secret holding the GitHub token (`namespace`, `key`), the Gitea target, and a `since` bound for the first sync. It reads the token from Kubernetes and passes it to git through an HTTP header, never the remote URL. It does not call the webserver API to learn what to mirror.

### Schema

One mirror per global `trigger_repositories` row. The repository gets `mirror_uri` and a second secret reference, `mirror_secret_id`: `secret_id` stays the upstream token the mirror reads, and `mirror_secret_id` is the Gitea read token the sensors use. When `mirror_uri` is set the flat API returns it as `uri` and the mirror secret as the credential, so sensors and DTOs are unchanged. Clearing it rolls back to polling GitHub.

## Needed alongside it

- Webserver: the webhook receiver, the event schema, and the `mirror_uri` and `mirror_secret_id` columns.
- Cluster: a deployment with persistent storage for the git cache and state; a service account with `get` on only the secrets it needs; a network policy with egress to GitHub, Gitea and the webserver and no ingress; a Gitea admin token for orgs, repositories and shadow users.
- Operations: an `fncli` command to register a mirror, check status and force a resync; health and status per repository (last sync, expired token); the first-sync `since` policy.
- Tests: integration tests against a real Gitea in Docker with recorded GitHub responses.

## Consequences

- The evaluation path no longer needs GitHub tokens or rate limits, and GitHub is polled once per repository however many projects use it.
- Results delivery and results PR sync still use GitHub, since those PRs live there.
- The ingest sensor can go, or shrink to a backstop.
- The service owns a small amount of state (cursors, the outbox) and a cross-namespace secrets grant.

## Open items

Gate on a spike before building. Behaviours of Gitea to verify:

- the pull request files endpoint on a `manually-merged` PR
- `manually-merged` with squash and rebase merges
- `merged_at` being the sync time rather than GitHub's
- whether a Gitea pull mirror can hold PRs at all (assumed not)

Also open: how far back the first sync goes, and who creates the Gitea org and read token per repository.

## Alternatives considered

- **A per-project mirror** (a Gitea org per project): isolates private repositories without the schema change, at the cost of duplicate mirrors and secrets. The fallback if 0019 is not done.
- **Gitea push webhooks to the webserver** instead of the service's own event: the mirror service already knows the PR facts from GitHub, and Gitea mirrors do not carry PR objects.
- **Real-time GitHub webhooks into the node**: rejected, they need an inbound route.
- **Argo CD**: it syncs git refs and sees no pull request objects.
