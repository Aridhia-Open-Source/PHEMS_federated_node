# 0021. Global resources, with a per-project link

- Status: Accepted (built)
- Supersedes [0003](0003-project-scoped-git-repositories.md) and, for the data model, [0004](0004-secrets-and-secret-providers.md) (the `SecretProvider` store is unchanged). Splits out of [0019](0019-global-resources-and-shared-pull-requests.md), which keeps the umbrella. Related: [0022](0022-git-provider-and-repository-identity.md) (what a repository is), [0023](0023-pull-requests-stored-once-fan-out-and-cursors.md) (pull requests), [0025](0025-switching-off-revoking-and-soft-delete.md) (off, revoked, deleted).

## Context

Secrets, datasets and trigger and results repositories belonged to one project. A repository or token used by two projects was registered twice, polled twice and its pull requests stored twice. A data controller could not grant access to something once.

## Decision

Each of the four is a **global resource** with no `project_id`, and a project reaches it only through a **link row** that holds the project's own settings.

| Global resource | Unique on (live rows) | Link table | Link settings besides `enabled`, `revoked`, `deleted_at` |
|---|---|---|---|
| `secrets` | `label` (and `key`) | `project_secrets` | none |
| `datasets` | `name` | `project_datasets` | none |
| `trigger_repositories` | `(provider_id, repo_path)` | `project_trigger_repositories` | `watch_dir`, `base_branch`, `initial_cursor`, `initial_cursor_number` |
| `results_repositories` | `(provider_id, repo_path)` | `project_results_repositories` | `target_dir`, `owned_by_federated_node` |

- Every global resource has its own `enabled` (default true). Every link has `enabled` (a person's switch) and `revoked` (the controller's withdrawal). Revoking never touches `enabled`.
- A link is unique on `(project_id, resource id)`. A project has at most one results link (unique on `project_id`), and one trigger link per repository, so it watches one directory per repository.
- Uniqueness is a partial index `WHERE deleted_at IS NULL`, so a soft-deleted label, name or link frees its slot (`_unique_when_live` in `001_baseline.py`).
- **`active` is a computed property on the link**, not a column: the global resource is enabled, the link is `enabled`, the link is not `revoked`. Trigger and results repositories add "and the provider is enabled" (`GitRepositoryMixin.active`). Every link DTO returns `enabled`, `revoked` and `active`.
- **URLs.** Global resource: `/global/datasets/<id>`, `/global/secrets/<label>`, `/global/repositories/triggers/<id>`, `/global/repositories/results/<id>`; `POST` is on the collection and only there. Link: the same tails under `/projects/<pid>/...`. A link is addressed by the global id (a secret by its label), never by the link row id.
- **Link verbs.** `PUT` creates a link (201) or, if it exists, replaces the project's settings (200; fields left out take defaults; `revoked` is not accepted). `PATCH` changes one setting. `DELETE` unlinks: a soft delete that also sets `revoked`. `GET` lists (inactive links included) or reads.
- **Admin only for now.** `POST`, `PATCH`, `DELETE` and `POST .../revoke` under `/global` need the `can_do_admin` scope (`admin-policy` only). `GET` under `/global` (datasets: `can_access_dataset`, for reading) and every `/projects/<pid>/...` link route need `can_admin_dataset` (admin or `System`, which Dagster uses). Setting `revoked` on a link also needs `g.caller_is_admin`. Auth is rewritten later, see [0014](0014-dar-rename-and-detached-auth.md).
- **Cross-project loops are forbidden.** `check_no_loop(provider_id, repo_path)` (`helpers/repository_loop.py`) takes every results link and every trigger link on the same repository, of any project, and refuses if a trigger watches the whole repository or its `watch_dir` overlaps a `target_dir`. It runs on trigger link PUT and PATCH and on results link PUT and PATCH, and rolls the change back.
- Creating a project's results link (the first PUT) needs the project locked (`require_locked`); a PUT naming a different results repository than the project's current one is a 409. Everything else needs no lock.
- Secret values never pass through the link API. `SecretDTO` has `key` and `namespace` (a reference), no values.

## Consequences

- One token, one poll and one set of pull requests per repository, however many projects use it. Each project keeps its own settings, cursors and results.
- Editing a global resource changes it for every linked project. The effect on running work is handled by [0024](0024-task-configuration-pinning.md), not by a lock.
- A global resource is created before it can be linked, and a resource used by one project is still a global resource with one link.
- The link id is not in the API, so a client needs the global id first (`GET /global/...`).
- After `DELETE`, a `PUT` creates a new row (the deleted one is hidden by `hide_deleted`), so `revoked` is false again and the trigger cursor restarts from the latest stored pull request. Unlinking then relinking is not the same as un-revoking.
- Deleting a global resource with live links is a 409 listing the projects, unless `?force=true` (`delete_global`, `helpers/soft_delete.py`).

## Alternatives considered

- **Keep per-project copies with a sync step**: rejected, it keeps the double polling and the double storage.
- **A flat compatibility API** (`/project_trigger_repositories`, link ids): rejected, the API shows the real model and the Dagster models were split to match.
- **One `status` enum instead of `enabled` and `revoked`**: rejected, a re-grant must restore the person's earlier switch.
- **Composite FK `(project_id, default_dataset_id)` to `project_datasets`** (planned in 0019): not done, see below.

## Where it lives

- PR #555 (branch `split/01-schema`): models in `webserver/app/models/` (`project_trigger_repository.py`, `project_results_repository.py`, `project_dataset.py`, `project_secret.py`, `trigger_repository.py`, `results_repository.py`, `secret.py`, `dataset.py`) and `webserver/migrations/versions/001_baseline.py`, edited in place per [0013](0013-baseline-migration-edited-in-place.md).
- PR #556 (branch `split/02-webserver`): routes `trigger_repositories_api.py`, `results_repositories_api.py`, `secrets_api.py`, `datasets_api.py`, `project_trigger_repositories_api.py`, and the dataset, secret and results link routes in `projects_api.py`; helpers `repository_loop.py`, `soft_delete.py`, `revoke.py`, `project_lock.py`; DTOs in `webserver/app/dtos/`.
- Tests: `webserver/tests/test_global_resources.py`, `test_trigger_repositories_and_links.py`, `test_results_and_delivery.py` (loop refusal, around line 171).

## Not built or open

- 0019 section 6 says `projects.default_dataset_id` is a composite FK to `project_datasets`. The code has a plain FK to `datasets.id` (`models/project.py`); `Project.resolve_dataset` checks the link and its `active`. `ProjectDataset.soft_delete` clears the default.
- 0019 section 1 lists the old columns (`uri`, `provider`, `api_uri` on repositories). They are `provider_id` and `repo_path` now, see 0022. It also omits `deleted_at` and the global `enabled`.
- A repository link's `active` does not look at the secret. A disabled secret only removes a repository from `GET /global/repositories/triggers?pollable=true`; its link still reports `active: true`. Open: should `active` include the secret?
- `check_no_loop` compares `(provider_id, repo_path)`, so the same Gitea registered under two provider hosts is two repositories to it and a loop through the alias is not seen.
- `owned_by_federated_node` is stored and returned, and this ADR does not say what it controls.
- Any admin or `System` token can `PUT` and `DELETE` links; only `revoked` is admin-checked. Per-project permission is for the auth rewrite.
- `whitelisted_images` stays project-agnostic and is not part of this change.
