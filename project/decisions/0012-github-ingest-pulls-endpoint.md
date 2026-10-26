# 0012. Ingest merged pull requests through the pulls endpoint, not search

## Context

The ingest needs the pull requests merged after a cursor. GitHub offers the search API and the list-pulls endpoint.

## Decision

`GithubAPI.get_new_merged_pulls` lists closed pull requests into the base branch (`GET repos/{repo}/pulls` with `state=closed`, `sort=updated`, `direction=desc`, `per_page` and `page`, and no `base` parameter), page by page, and keeps those with `merged_at` after the cursor. Matching the base branch is done in the webserver fan-out, per project resource ([0011](0011-pull-requests-stored-once-fan-out-and-cursors.md)). It stops at the first pull request whose `updated_at` is not after the cursor, since `updated_at` is never before `merged_at`. The cursor is the repository's global poll cursor ([0011](0011-pull-requests-stored-once-fan-out-and-cursors.md)). The ingest runs once per pollable global trigger repository ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)); it fetches each pull request's files and posts the batch to the backend, which stores it and fans it out.

## Consequences

- No search rate limit (30 requests a minute) and no index lag that could let the cursor pass an unindexed pull request.
- Cost grows with the pull requests updated (not only merged) since the cursor. None is missed: a pull request merged after the cursor was also updated after it.
- Only merged pull requests are recorded; closed-unmerged ones are not.
- Pull request numbers are unique per repository, so re-ingesting is safe.

## Alternatives considered

- **Search API (`is:merged merged:>cursor`):** the limit and lag above.
- **Webhooks from the provider:** the node polls so that it needs no inbound route.
- **Webhooks into the node:** rejected; the node stays outbound-only.
- **Argo CD to mirror repositories:** it sees git refs and no pull request objects, so it cannot supply merged pull requests.
- **Real-time updates:** never required; the poll interval is enough.

The mirror service that copies pull requests into the node's Gitea is developed on branch `moonshot/gitea-mirror`; the node sees it as a `gitea` git provider.
