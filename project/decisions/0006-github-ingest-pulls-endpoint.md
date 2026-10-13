# 0006. Ingest merged pull requests through the pulls endpoint, not search

- Status: Accepted

## Context

The ingest sensor needs the pull requests merged after a cursor. GitHub offers the search API and the list-pulls endpoint.

## Decision

`GithubAPI.get_new_merged_pulls` lists closed pull requests into `base_branch` (`GET repos/{repo}/pulls?state=closed&base=...&sort=updated&direction=desc`), page by page, and keeps those with `merged_at` after the cursor. It stops at the first pull request whose `updated_at` is not after the cursor, since `updated_at` is never before `merged_at`. The cursor is `max(merged_at)` of what is stored, else the repository's `initial_cursor` ([0003](0003-project-scoped-git-repositories.md)). The ingest sensor then fetches each pull request and saves the batch as `UNKNOWN`.

## Consequences

- No search rate limit (30 requests a minute) and no index lag that could let the cursor pass an unindexed pull request.
- Cost grows with the pull requests updated (not only merged) since the cursor. None is missed: a pull request merged after the cursor was also updated after it.
- Only merged pull requests are recorded; closed-unmerged ones are not.
- Pull request numbers are unique per repository (`uq_pr_repo_number`), so re-ingesting is safe.

## Alternatives considered

- **Search API (`is:merged merged:>cursor`)**: rejected for the limit and lag above.
- **Webhooks**: not chosen, the node polls so it needs no inbound route.
