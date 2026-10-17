# Gitea mirror service

Mirrors the merged pull requests of GitHub repositories into the node's own Gitea, so the evaluation path reads locally. It knows nothing about the federated node: no webserver calls, no shared schema. Design: [ADR 0020](../project/decisions/0020-gitea-mirror-service.md). Spike findings: [SPIKE.md](SPIKE.md).

It is outbound only. It polls GitHub, pushes to a normal Gitea repository, and tells registered webhook endpoints when a pull request has been mirrored.

## Configuration

Environment variables, all required unless noted:

- `GITEA_MIRROR_API_TOKEN`: the bearer token every API route (except `/health`) checks. The app fails at startup if it is unset.
- `GITEA_MIRROR_DB_USER`, `GITEA_MIRROR_DB_PASSWORD`, `GITEA_MIRROR_DB_HOST`, `GITEA_MIRROR_DB_PORT`, `GITEA_MIRROR_DB_NAME`: the `gitea_mirror` Postgres database.
- `GITEA_MIRROR_DB_SSL` (optional): SSL mode for the connection.
- `GITEA_MIRROR_GITEA_URL`, `GITEA_MIRROR_GITEA_TOKEN`: the Gitea base URL and an admin token.
- `GITEA_MIRROR_GIT_CACHE_DIR`: where the bare cache repository lives (the chart mounts an emptyDir at `/tmp/git-cache`; a restart re-fetches).
- `GITEA_MIRROR_SYNC_INTERVAL_SECONDS`: seconds between sync rounds.

The image entrypoint is `python -m app.runner`: it serves the API with waitress and runs the sync timer loop (sync every enabled mirror, then deliver due webhooks) in a thread beside it.

GitHub tokens and webhook HMAC keys are not env vars. A mirror or webhook names a Kubernetes secret (`secret_namespace`, `secret_key`) and the service reads its `token` field through the in-cluster API.

## API

All routes need `Authorization: Bearer <GITEA_MIRROR_API_TOKEN>`, except `GET /health`. Bodies are JSON; unknown fields are rejected with 400. `fncli mirror` wraps these.

Mirrors (`upstream_uri` is an https URL; fields are `upstream_uri`, `secret_namespace`, `secret_key`, `gitea_owner`, `gitea_repo`, `base_branch`, `enabled`):

- `GET /mirrors`, `POST /mirrors`, `GET|PATCH|DELETE /mirrors/<id>`. Creating a mirror starts its cursor at now (no backfill of old pull requests) and preloads shadow users; the response has `users_sync` (ok, skipped or failed). A duplicate upstream URI or Gitea repository is 409.
- `GET /mirrors/<id>/status`: `cursor`, `last_sync_at`, `last_success_at`, `last_error`, `prs_mirrored`, `token_expired`.
- `POST /mirrors/<id>/resync`: runs a sync for the mirror now. 200 `{status, mirrored}`; 409 when another sync holds the mirror's lock; 502 on a GitHub, Gitea or git error. It ignores the rate-limit pause.
- `POST /mirrors/<id>/users/sync`: creates shadow users for the upstream contributors and collaborators. Returns `users`, `created`, `existing`.

Webhooks (fields `url` (http or https), `secret_namespace`, `secret_key`, `mirror_id` (null for all mirrors), `enabled`):

- `GET /webhooks`, `POST /webhooks`, `GET|PATCH|DELETE /webhooks/<id>`.
- `POST /webhooks/<id>/test`: sends a signed `ping` now (redirects are not followed); 502 `{status: failed, reason: <exception class>}` if it fails.

Input rules (400 otherwise). Mirrors: `upstream_uri` must be `https://github.com/<owner>/<repo>` (no userinfo, port, query or fragment); `gitea_owner`/`gitea_repo` only `[A-Za-z0-9_.-]` (no `..`); `base_branch` a plain branch name (no `:`, `..`, spaces, control characters); `secret_namespace`/`secret_key` Kubernetes names. Webhooks: the secret must exist and have its `token` field at registration. The URL must be http(s) without credentials and its host must resolve. In-cluster receivers (`*.svc.cluster.local`, private ranges) are allowed by default; loopback, link-local (including the 169.254.169.254 metadata address), unspecified and the Kubernetes API server are always refused. Set `GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE=false` to refuse private ranges too. `GITEA_MIRROR_API_TOKEN` must be set and non-empty or the service will not start.
- `GET /webhooks/<id>/deliveries[?status=pending|delivered|failed]`: the latest 100, newest first.

## Sync algorithm

Per mirror, under a per-mirror lock, from the cursor (an `updated_at` time, starting at mirror creation):

1. Fetch merged pull requests into the base branch from GitHub (conditional requests, oldest first) and the refs `refs/pull/*/head`.
2. Push the branches to the Gitea repository as they are, and each PR head as a `pr/<n>` branch. A normal repository rejects pushes into `refs/pull/*`, and Gitea writes its own refs there.
3. Replay the PRs in `merged_at` order. For each: force-push the Gitea base branch to `merge_commit_sha^1`, open the Gitea pull request from `pr/<n>` as the shadow user (admin `Sudo` header), fast-forward the base to `merge_commit_sha`, and mark the PR `manually-merged` at that commit. The order matters: if the base already holds the head, the PR files endpoint is empty for merge-commit and fast-forward merges.
4. Record the pull request row (`unique(mirror_id, number)`, storing both numbers) before the cursor advances, so a repeat after a crash is harmless.
5. Enqueue a webhook delivery for each matching webhook.

The repository is created with `allow_manual_merge` on. Gitea's own PR number differs from GitHub's, and `merged_at` in Gitea is the sync time, which cannot be set, so the event carries GitHub's.

## Webhook event

`POST` to the endpoint with the JSON body defined in [schema/pull_request.mirrored.json](schema/pull_request.mirrored.json):

```json
{
  "event": "pull_request.mirrored",
  "delivery_id": "17",
  "mirror": {"upstream_uri": "https://github.com/org/repo", "gitea_owner": "mirrors", "gitea_repo": "repo"},
  "number": 126,
  "gitea_pr_number": 1,
  "title": "...",
  "author": "github-login",
  "merged_at": "2025-01-30T19:03:52Z",
  "merge_commit_sha": "02fbd091..."
}
```

`number` and `merged_at` are GitHub's. Read the files with `gitea_pr_number` (`/pulls/{index}/files`).

Headers:

- `X-Gitea-Mirror-Signature`: `sha256=<hex>`, the HMAC-SHA256 of the raw body keyed with the webhook's secret.
- `X-Gitea-Mirror-Delivery`: the delivery id, the same as `delivery_id`. Drop repeats of an id you have handled.
- `X-Gitea-Mirror-Event`: `pull_request.mirrored`, or `ping` for a test.

Deliveries come from an outbox: at-least-once, 5 attempts with backoff from 30 seconds, doubling. Receivers must be idempotent. A 2xx response counts as delivered.

## Running tests

```bash
cd gitea-mirror
./run_tests.sh
```

Postgres runs in Docker. Each run uses its own Compose project (`gm-test-*`) so parallel runs do not collide. The dev requirements add `jsonschema` and `rfc3339-validator` for the event schema tests.

## Database

Alembic migrations (`migrations/`) create `mirrors`, `mirror_state`, `mirrored_pull_requests`, `webhooks` and `webhook_deliveries`.

## Known gaps

- A crash between opening the Gitea pull request and inserting its row leaves an open PR, and the retry's open will fail.
- A multi-commit fast-forward PR shows only its last commit's files (the base is rewound to `merge^1`, as the spike prescribes).
- Branches deleted upstream are not deleted on Gitea (the push has no `--prune`, which would drop `pr/*`).
- The rate-limit reset time is held in memory by the timer loop; a restart costs one extra 403.
