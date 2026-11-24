# 0038. One outbound client layer for nexus-api

Status: Proposed, 2026-11-22.

## Context

nexus-api calls Keycloak, Dagster, git providers, dataset databases and Kubernetes. Each call site set its own
timeout, or none: Keycloak's ~38 calls had no timeout at all, Dagster used 30s, the git calls 5s and 10s. There were
no retries, no 429 handling, no connection reuse and no typed error, so an outage surfaced as a 500 or a hung worker.
`/health_check` is open to anyone and called Keycloak on every request with a 30s timeout (issue #674).

## Decision

- Every outbound HTTP call in nexus-api goes through `app/clients/outbound.py`: `session("<service>")` returns one
  shared `requests.Session` per service.
- Each session has a default `(connect, read)` timeout (`OUTBOUND_CONNECT_TIMEOUT` 3s, `OUTBOUND_READ_TIMEOUT` 10s).
  A service can override it (Dagster: 30s read), and so can a single call (`/health_check`: 2s/3s).
- Only a 429 is retried, 3 times with backoff and honouring `Retry-After`, for every method, POST included, since a
  429 means the request was not processed. A read timeout is never retried, so a write is never repeated.
- A timeout is `OutboundTimeout` (504) and a connection failure is `OutboundError` (502), both rendered by the
  usual error handler.
- The sessions are shared across users, so they keep no cookies and never carry an `Authorization` header of their
  own.
- `ttl_cache` is an opt-in cache for idempotent reads only, never writes. Under a lock, a flood makes one call per
  window, and failures are cached too. `/health_check` caches Keycloak's answer for 5s.
- Dataset connections and Kubernetes API calls get equivalent timeouts.
- A unit test fails on any bare `requests.<verb>(` call in `nexus/api/app`, so new services go through the layer.
- The values match `nexus_client.http`, which Dagster, fncli and the operator use: 10s default timeout, 3 retries
  on 429, backoff 0.5. The code is a small copy rather than a shared import, because `nexus_client` is a client of
  nexus-api with base-URL sessions and bearer-token state. It is not a generic outbound layer, and making nexus-api
  depend on it would add a build context and pinned path dependency for about 60 lines.

## Consequences

- Every outbound call has a timeout, and a dependency outage is a 502 or 504 instead of a hang or a 500.
- `/health_check` makes at most one Keycloak call per 5s, however many requests arrive.
- The two copies (nexus-api and nexus_client) can drift; this ADR records the shared values.

## Alternatives considered

- Extract a shared outbound package used by nexus-api and nexus_client: rejected for now, see above. Revisit if a
  third copy appears.
- Per-call timeouts without a layer: this is how it was, and it led to the inconsistency above.

## Open questions

- nexus_client retries a 429 only on urllib3's default idempotent methods, so a POST that gets a 429 is not retried
  there, unlike in nexus-api. Should it match?
