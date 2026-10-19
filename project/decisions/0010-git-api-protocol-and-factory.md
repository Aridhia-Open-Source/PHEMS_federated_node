# 0010. GitAPI protocol and GitAPIFactory over Gitea and GitHub

## Context

The node must work against a self-hosted Gitea (in-cluster, for development and some deployments) and GitHub, without sensors branching on the provider.

## Decision

- `GitAPI` is a `Protocol` with the operations the sensors and delivery need: `get_pull_request`, `get_new_merged_pulls`, `get_pull_request_files`, `get_file_contents`, `get_default_branch`, `find_pull_request_by_branch`, `create_pull_request`. `GithubAPI` and `GiteaAPI` implement it over their own HTTP clients.
- `GitAPIFactory.for_repository(repo)` builds the client from the repository's provider (`type`, `api_uri`) and the token of the repository's secret ([0007](0007-secrets-and-secret-providers.md)). It is the Dagster resource `git_apis`. An unknown provider type raises.
- The provider is a global entity ([0006](0006-global-resources-and-project-links.md)): `type` is validated in the backend against `GitProviderType` (`github`, `gitea`), and its `api_uri` is required and must be on the provider's own host, since tokens are sent to it. A Gitea provider's API base is `https://<host>/api/v1` or the in-cluster `http` address, set explicitly ([0019](0019-gitea-port-4000-and-localhost-forward.md)).

## Consequences

- Sensors and delivery are provider-neutral; adding GitLab is a client, a `GitProviderType` value and a factory case.
- Provider quirks stay in the clients (for example GitHub's test-merge `merge_commit_sha` on unmerged pull requests is dropped by the callers).
- `repo_path` (`owner/name`) is the unit both clients take, which suits GitHub and Gitea; nested GitLab groups would need provider handling.

## Alternatives considered

- **An abstract base class:** a Protocol keeps the clients independent.
- **Provider inferred from the host:** self-hosted hosts are arbitrary.
