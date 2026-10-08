# 0005. GitAPI protocol and GitAPIFactory over Gitea and GitHub

- Status: Accepted

## Context

The node must work against a self-hosted Gitea (in-cluster, for development and some deployments) and GitHub, without sensors branching on the provider.

## Decision

- `GitAPI` is a `Protocol` with the operations the sensors need: `get_pull_request`, `get_new_merged_pulls`, `get_pull_request_files`, `get_file_contents`, `get_default_branch`, `find_pull_request_by_branch`, `create_pull_request`. `GithubAPI` and `GiteaAPI` implement it over their own HTTP clients.
- `GitAPIFactory.for_repository(repo)` builds the client from `repo.provider`, `repo.api_uri` and the token of the repository's secret. It is the Dagster resource `git_apis`. An unknown provider raises.
- `provider` is validated in the backend against `GitProvider` (`github`, `gitea`).
- `api_uri` is stored on the repository (the scheme is stripped from `uri`) and is **optional on create**: `GitProvider.default_api_uri` gives `https://api.github.com` for GitHub and `https://<host>/api/v1` for Gitea.

## Consequences

- Sensors and delivery are provider-neutral; adding GitLab is a client, a `GitProvider` value and a factory case.
- Provider quirks stay in the clients (e.g. GitHub's test-merge `merge_commit_sha` on unmerged pull requests is dropped by the callers).
- The default Gitea `api_uri` assumes https, so the in-cluster http Gitea must set `api_uri` explicitly.

## Alternatives considered

- **Abstract base class**: rejected, a Protocol keeps the clients independent.
- **Provider inferred from the host**: rejected, self-hosted hosts are arbitrary.
