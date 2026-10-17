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

There is no route to redeliver. After a receiver outage longer than the retry window, deliveries end up `failed`; an operator can put them back in the queue from a shell in the pod with `delivery.requeue_failed(session, webhook_id=None)` (see its docstring in `app/delivery.py`; it resets attempts and returns the number requeued).

`GET /health` needs no token. It returns 200 `{"status": "ok"}`, or, when the sync thread is registered (the container runner), `{"status": "ok", "sync": {"alive": true, "last_tick_at": "<time>"}}`. It returns 503 with `status: error` if the database does not answer, the sync thread is dead, or it has not ticked within 3 times the sync interval.

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
- `X-Gitea-Mirror-Delivery`: the delivery UUID, the same as `delivery_id` in the body. It is stable across retries of the same delivery.
- `X-Gitea-Mirror-Event`: `pull_request.mirrored`, or `ping` for a test.
- `X-Gitea-Mirror-Timestamp`: the send time. It is **not** covered by the signature.

Receiver guidance: verify the HMAC over the raw body bytes; dedupe on the delivery id (remember the ids you have handled); treat the timestamp as advisory only. Because it is unsigned, a captured request can be replayed with a fresh timestamp, so the timestamp is no replay protection, the delivery id is.

Deliveries come from an outbox: at-least-once, 5 attempts with backoff from 30 seconds, doubling. Receivers must be idempotent. Only a 2xx response counts as delivered; redirects are not followed and a 3xx counts as a failure. Each delivery is claimed under a lease, and an error on one delivery (for example a webhook whose secret lacks `token`) does not stop the others.

## Sync behaviour

- The Gitea base branch is restored to the upstream tip even when a PR fails, and a PR that keeps failing is quarantined (recorded as an error) so it does not block the mirror.
- Before opening a PR the engine looks for an existing Gitea PR for head `pr/<n>` and resumes from there, so a retry does not open a duplicate.
- Shadow users get the prefix `gh-`, so a GitHub login cannot collide with the Gitea admin or an organisation name; an existing non-shadow account of that name is an error.
- The GitHub token is only sent to github.com, and git credentials are passed through `GIT_CONFIG_COUNT` environment variables rather than command-line arguments.
- The cursor only moves past PRs that are settled (mirrored or history), so PRs with equal `updated_at` are not skipped, and upstream branches that clash with `pr/<n>` are reported rather than overwriting PR refs.
- After the first push the Gitea default branch is set to the mirror's base branch (Gitea would otherwise pick a `pr/<n>` branch).

## Deploying the chart

The `gitea-admin-init` job is a Helm `post-install,post-upgrade` hook. Besides the admin user it creates the Gitea access token and stores it in the secret `gitea-mirror-gitea-token` (`giteaMirror.giteaToken.secret`); an existing secret is kept. The mirror pod reads `GITEA_MIRROR_GITEA_TOKEN` from that secret and cannot start (CreateContainerConfigError) until it exists. `helm install --wait` (or `--atomic`) waits for the Deployment to be ready before it runs post-install hooks, so it deadlocks until the timeout. Install without `--wait`: the pod starts by itself once the job has created the secret. Check with `kubectl get secret gitea-mirror-gitea-token` and `kubectl rollout status deploy/gitea-mirror`. The chart refuses to render with `giteaMirror.replicaCount` other than 1.

## Running tests

```bash
cd gitea-mirror
./run_tests.sh
```

Postgres runs in Docker. Each run uses its own Compose project (`gm-test-*`) so parallel runs do not collide. The dev requirements add `jsonschema` and `rfc3339-validator` for the event schema tests.

## Database

Alembic migrations (`migrations/`) create `mirrors`, `mirror_state`, `mirrored_pull_requests`, `webhooks` and `webhook_deliveries`.

## Known gaps

- Gitea accepts a second pull request for the same head, so a failure after a Gitea PR was opened but before its row is recorded (a crash, or a Gitea error on push or merge) must not be retried by opening again. The sync engine looks for an existing PR for head `pr/<n>` before opening one and resumes from the merge step.
- A multi-commit fast-forward PR shows only its last commit's files (the base is rewound to `merge^1`, as the spike prescribes).
- Branches deleted upstream are not deleted on Gitea (the push has no `--prune`, which would drop `pr/*`).
- The rate-limit reset time is held in memory by the timer loop; a restart costs one extra 403.
