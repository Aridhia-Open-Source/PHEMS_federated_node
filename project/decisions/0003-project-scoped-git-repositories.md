# 0003. Project-scoped trigger and results repositories

- Status: Accepted

## Context

The first design had one global set of repositories and credentials. A federated node serves several projects and each needs its own trigger repository (where analysts merge specs) and results destination, with its own credentials.

## Decision

- `trigger_repositories` and `results_repositories` both belong to a `project` and share `GitRepositoryMixin`: `project_id`, `uri`, `provider`, `api_uri`, `secret_id`.
- `uri` is stored without scheme and lower-cased. `repo_path` (`owner/repo`) is not stored: it is the last two segments of `uri`. This is right for GitHub and Gitea only (nested GitLab groups would need provider handling).
- A trigger repository adds `watch_dir`, `base_branch`, `initial_cursor`. The cursor sent to the provider is `max(merged_at)` of its pull request triggers, else `initial_cursor`; `initial_cursor` cannot change once pull requests exist.
- A results repository adds `target_dir` and `owned_by_federated_node`. **One results repository per project** (`uq_results_repositories_project`).
- The secret is referenced by composite foreign key `(project_id, secret_id)` to `secrets (project_id, id)`, so a repository can only use a secret of its own project. `(project_id, uri)` is unique per table.
- Tasks run only for `enabled` projects (default false); the sensors skip the others.

## Consequences

- The foreign keys to a project are `RESTRICT`, so `DELETE /projects/<id>` removes tasks, datasets, repositories and secrets explicitly in dependency order (the remaining API triggers go by `ON DELETE CASCADE`), and the stored secret values after the commit.
- A project cannot deliver to two destinations. Adding one would relax `uq_results_repositories_project`; `results` is already keyed by `(task, results_repository)`.
- The trigger repository check (`GET /projects/<id>/healthcheck`) reaches the provider through `api_uri` with the repository's own token.

## Alternatives considered

- **Global repository and token via env (`GH_TOKEN`)**: rejected, see [0004](0004-secrets-and-secret-providers.md).
- **Derive the secret from the uri**: rejected, repositories of one project may share a credential.
- **Store `repo_path`**: rejected, it duplicates `uri`.
