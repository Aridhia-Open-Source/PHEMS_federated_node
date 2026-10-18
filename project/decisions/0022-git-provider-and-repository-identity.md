# 0022. GitProvider and the identity of a repository

- Status: Accepted (built)
- Supersedes the repository columns of [0003](0003-project-scoped-git-repositories.md) and the `uri`/`api_uri`/`provider` columns in section 1 of [0019](0019-global-resources-and-shared-pull-requests.md). Builds on [0021](0021-global-resources-and-project-links.md).

## Context

A repository used to carry its own `uri`, `provider` string and `api_uri`, and the token it used was found through the project. Two rows could name the same repository in different spellings (`https://github.com/a/b.git`, `github.com/A/B/`), and the host's API address was repeated on every row and could point anywhere the token would then be sent.

## Decision

### The provider

- `git_providers` is a global table (`models/git_provider.py`): `name`, `type` (`github` or `gitea`, `GitProviderType`), `uri` (the web address), `api_uri` (the API base URL), `enabled`, `deleted_at`. `name` and `uri` are each unique among live rows.
- Routes (`git_providers_api.py`): `GET /global/providers[/<id>]`, and `POST`, `PATCH`, `DELETE` with the `can_do_admin` scope. A duplicate `name` or `uri` is a 409 (`_check_unique`). `DELETE` is a 409 while any trigger or results repository is on the provider, otherwise a soft delete. `GET /global/providers/<id>/healthcheck` is in `healthcheck_api.py`.
- A repository on a **disabled provider is inactive**: `GitRepositoryMixin.active` is `enabled and provider.enabled`, and a link's `active` includes it. Switching a provider back on moves every trigger link's cursor to now (`skip_gap`), so nothing merged while it was off gets a trigger ([0023](0023-pull-requests-stored-once-fan-out-and-cursors.md)).

### The repository

- A trigger or results repository is `provider_id` + `repo_path` + `secret_id` + `enabled` (`GitRepositoryMixin`, `models/git_repository.py`). It has no `uri` column: `uri` is derived as `provider.uri + "/" + repo_path`.
- `(provider_id, repo_path)` is unique among live rows, separately for trigger and for results repositories. A duplicate `POST`, or a `PATCH` of `provider_id` onto an existing one, is a 409.
- `secret_id` is the repository's own token (key `TOKEN`), one per repository, so a token is limited to what that repository needs. Repositories may share a secret, by choice. A disabled secret is a 400 on create and on patch, unless it is the one already in use (`Secret.get_enabled_by_label`).
- Only `provider_id`, `secret_label` and `enabled` can be patched. `repo_path` cannot (`patch_repository` rejects other fields); to move a repository, create a new one.

### Normalisation and validation (`helpers/git_uri.py`)

- `normalise_provider_uri`: scheme `http` or `https` required, host required, no `user@`, lowercase, default port (443, 80) and trailing slash dropped, a path is kept. Applied by `@validates('uri')`.
- `normalise_repo_path`: strip slashes and `.git`, lowercase, exactly two non-empty segments `owner/name`. Applied by `@validates('repo_path')`.
- `validate_api_uri`: http(s), a host, no credentials, and on the provider's own host and port, because repository tokens are sent to it. The one exception is `github.com`, whose API host must be `api.github.com`. `GitProvider.api_uri` is validated after `uri`, and a `PATCH` of `uri` re-checks `api_uri`.
- `normalise_repo_uri` (`host[:port]/owner/repo`, no scheme) is used by `RepositoryUriRequest` for a task's `repository` field. `Task.validate` matches it against each trigger link's `uri` and refuses a repository linked to more than one project (400).
- `type` is checked against `GitProviderType`; a value Dagster has no client for is refused.

### One uri, one provider

- `uri` is unique, so the same host cannot be registered twice. Two rows for one host would give one repository two identities (two `(provider_id, repo_path)` keys), each with its own cursor, stored pull requests and link set, and a fan-out that runs twice for the same pull request.
- Tests that need two providers use one Gitea under two host names: `fncli simulate-setup` creates a Kubernetes `ExternalName` service (`gitea-b`, `dagster/fncli/cmds/simulate.py`, `apply_alias`) and registers two providers, `uri` unique each.
- `html_url` in a Gitea response comes from Gitea's own `ROOT_URL` (`http://gitea.<ns>.svc:4000`, `k8s/federated-node/templates/gitea-deployment.yaml`), not the host the node called. The node does not build any address from it: it clones and calls `provider.api_uri`. It stores a results pull request's `html_url` as the result's `url` (`dagster/app/delivery/results.py`, `pull_request_sync.py`) for display only, so that link may show a different host than the provider's `uri`.

## Consequences

- One spelling per repository, so lookups and uniqueness work on strings.
- A provider's `api_uri` is edited in one place; tasks created earlier are pinned to the old one and fail instead of running against the new ([0024](0024-task-configuration-pinning.md)).
- A token cannot be sent to a host other than the provider's, short of editing the provider (an admin action).
- The same Gitea under two names is still two providers, so the loop check and shared-repository sharing do not see through the alias.

## Alternatives considered

- **`uri`, `provider` and `api_uri` on each repository** (the previous shape): rejected, repeated and unchecked.
- **A token per provider**: rejected, a leaked token would reach every repository on the host; a token per repository keeps least privilege.
- **Allow duplicate provider uris with different names**: rejected, see "One uri, one provider".
- **Derive `api_uri` from `type` and `uri`**: not done; Gitea and GitHub Enterprise paths vary, so it is stored and validated.

## Where it lives

- PR #555 (branch `split/01-schema`): `models/git_provider.py`, `git_provider_type.py`, `git_repository.py`, `trigger_repository.py`, `results_repository.py`, `webserver/app/helpers/git_uri.py`, `001_baseline.py` (`git_providers`, the two repository tables).
- PR #556 (branch `split/02-webserver`): `git_providers_api.py`, the repository routes in `trigger_repositories_api.py` and `results_repositories_api.py`, `dtos/git_provider.py`, `dtos/repository_uri.py`.
- Dagster reads the provider through `repo.provider.api_uri` (`dagster/app/definitions/sensors/git/base.py`).
- Tests: `webserver/tests/test_git_uri.py`, `test_git_providers.py`, `test_global_resources.py`.

## Not built or open

- Nothing stops two providers with different names and different hosts that reach the same server (the Gitea alias). Open: reject by resolving the host, or leave it to the admin.
- A provider's `type` and `uri` can be patched while repositories use it; the check is the pinning in 0024, not a refusal.
- `html_url` is stored as given. Open: rewrite it onto the provider's `uri` for display.
- That Gitea builds `html_url` from `ROOT_URL` is Gitea's behaviour, taken from its configuration, not tested here.
