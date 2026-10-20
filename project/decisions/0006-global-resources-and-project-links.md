# 0006. Global resources, linked to projects

## Context

A federated node serves several projects. The same upstream repository, credential or dataset is used by more than one of them, and a data controller must be able to grant a project access to something once, without that project (or its analysts) creating or holding it. Registering a resource per project would also mean polling the git provider and storing every pull request once per project.

## Decision

### Global resources, with a per-project link

Global resources are created by the data controller (admin role) and have no `project_id`. All carry `enabled` and `deleted_at`; all but `secrets` also carry `revoked`.

| Table | Columns (besides `id`, flags, timestamps) |
|---|---|
| `secrets` | `label` (unique), `description`, `provider` (`K8S`), `key` (unique), `namespace` ([0007](0007-secrets-and-secret-providers.md)) |
| `git_providers` | `name` (unique), `type` (`github` or `gitea`), `uri` (unique), `api_uri` |
| `trigger_repositories` | `provider_id`, `repo_path` (`owner/name`), `secret_id`; unique on `(provider_id, repo_path)` |
| `results_repositories` | `provider_id`, `repo_path`, `secret_id`; unique on `(provider_id, repo_path)` |
| `datasets` | `name` (unique), `host`, `port`, `type`, `read_schema`, `write_schema`, `extra_connection_args`, `secret_id` |

A project reaches a resource only through its own link row, which holds that project's configuration and its own `enabled` and `revoked` flags:

| Table | Columns (besides `id`, flags) |
|---|---|
| `project_trigger_repositories` | `project_id`, `trigger_repository_id`, `watch_dir`, `base_branch`, `initial_cursor`, `initial_cursor_number`; unique on `(project_id, trigger_repository_id)` |
| `project_results_repositories` | `project_id` (unique), `results_repository_id`, `target_dir`, `owned_by_federated_node` |
| `project_datasets` | `project_id`, `dataset_id`; unique on the pair |
| `project_secrets` | `project_id`, `secret_id`; unique on the pair (the flags are stored, but nothing reads them) |

The link is the permission boundary: a project can use a repository, dataset or the secret behind it only through a link the controller created. The API returns secret references only, never values.

A **git provider** is a global entity of its own: the web `uri` (`https://github.com`, normalised, lower case, no default port) and the `api_uri` the tokens are sent to, which must be on the provider's own host (`api.github.com` for `github.com`). A repository names its provider and its `repo_path`; its `uri` is the two joined. Provider flags apply to every repository on it. A provider with repositories cannot be deleted.

### Active

An `enabled` flag is a person's switch, `revoked` is the controller withdrawing access, and a link is **active** only when its global resource (and, for a repository, its provider) is enabled and not revoked and the link itself is enabled and not revoked. A link accepts triggers only if its project is also enabled and not revoked, and a disabled or revoked project accepts no task, from a pull request or the API (409). The rules for each flag, soft delete and what each state does to work in flight are in [0008](0008-enabled-revoked-and-soft-delete.md).

### URL layout

Datasets, secrets, trigger repositories and results repositories are all resources: each exists globally and is linked to projects. Every URL is either global or under one project.

| Scope | Path | Methods |
|---|---|---|
| Global | `/global/datasets/<id>`, `/global/secrets/<label>`, `/global/providers/<id>`, `/global/repositories/triggers/<id>`, `/global/repositories/results/<id>` | `POST` on the collection creates; `GET`, `PATCH` and `DELETE` manage |
| Project | `/projects/<pid>/datasets/<id>`, `/projects/<pid>/secrets/<label>`, `/projects/<pid>/repositories/triggers/<id>`, `/projects/<pid>/repositories/results/<id>` | `GET` lists or reads the link; `PUT` links (201 first time, 200 after); `PATCH` changes the project's settings; `DELETE` unlinks |

- **One id.** Project paths use the global resource's id (a secret's label), never the link row's id; a project's view of a resource is addressed by `(project_id, resource id)`.
- **Projects never create resources.** `POST` exists only under `/global`. A resource only one project uses is a global resource linked to that one project.
- **`PUT` replaces** the project's own settings; fields left out take their defaults, and `PATCH` changes one. `revoked` is the controller's: revoking and un-revoking are admin-only and only through `PATCH`; a `PUT` with `revoked` in the body is a 400.
- **Project routes return inactive links too**, with `enabled`, `revoked` and a computed `active`. Hiding them would break work in flight in Dagster (delivery and the results sync resolve a result's repository by id, including through an inactive link). The ingest, evaluate and launcher sensors filter on active links.
- **Sub-resources nest under their parent, in its scope.** A pull request's facts are under the global repository (`/global/repositories/triggers/<id>/pull_requests`, including the batch ingest); a project's trigger for it is under the project's link (`/projects/<pid>/repositories/triggers/<id>/pull_requests/<number>`).
- **Results are project-scoped:** `/projects/<pid>/results` ([0004](0004-polymorphic-result-and-forward-only-state.md)).
- **No cross-project lists.** Clients do not fetch lists and filter them in Python: every filter they need is a query option on the list endpoint (`?pollable=true`, `?enabled=true`, `?active=true`, `?active_link=true`, `?state=`, `?step=`).
- **Global secrets, datasets and repositories are addressed by id or label only**, never by name in the URL; `DatasetDTO.url` uses the id.
- **One results repository per project** (`UNIQUE(project_id)` on the link). `results` is already keyed by `(task, results link)`, so adding more would relax that constraint only. Linking a project's results repository needs the project disabled.

### Datasets and the default dataset

- A task reaches its dataset through `task_specs.dataset_id`. "The dataset belongs to this project" means the project has a link to it, and it must be active (`Project.resolve_dataset`, `Task.validate`).
- `projects.default_dataset_id` points at `datasets.id`; the first dataset linked to a project becomes its default. A spec that names no dataset runs on the default, if there is one.
- `task_specs.dataset_id` and `tasks.task_spec_id` are `RESTRICT`, so a dataset a task ran on cannot be deleted for real; deletion is soft ([0008](0008-enabled-revoked-and-soft-delete.md)).
- Dataset-level authorisation is not part of this design ([0017](0017-authorization-detached-from-dar-and-keycloak.md)).

### Other rules

- **Cross-project loops.** `check_no_loop` forbids a results link that writes into a directory a trigger link of any project watches, in the same repository, and a trigger link that watches the whole repository when a results link writes to it.
- **Shared by design.** Editing a global resource affects every project linked to it; the tasks it affects fail or are `STALE` ([0009](0009-task-pinned-to-its-configuration.md)). Rotating a secret reaches every project using it.
- **`delete_project`** soft deletes the project and its links only. It does not touch secrets, datasets, repositories or their stored values.
- **Admin role.** Creating global resources and writing their flags requires the admin role.
- **`whitelisted_images`** are not part of this pattern; they stay per project ([0017](0017-authorization-detached-from-dar-and-keycloak.md)).
- **One baseline migration.** The schema is the single Alembic revision `001_baseline` (`webserver/migrations/versions/001_baseline.py`); a schema change is made in it and environments are recreated. The Dagster database has its own, unrelated schema.
- **Dagster and fncli models.** Dagster's `Secret` needs only `key`, `namespace` and `provider`; its repository and dataset models are split into a global model and a link model, with `extra="allow"` so a new backend field does not break an older client. `dagster/fncli` imports them from `dagster/app`.

## Consequences

- One credential, one set of stored pull requests and one provider poll per repository, however many projects use it; each project keeps its own state, results and cursors.
- The controller's grant is the link row; revoking it stops only that connection.
- Cross-service shape drift (backend, Dagster, fncli) shows only in tests that parse the same responses.
- With one baseline migration there is no upgrade path between schema versions; this has to change at the first deployment that holds data worth keeping, when new revisions are added and `001_baseline` is frozen.
- `GET /projects/<id>/repositories/results` returns the project's link with its flags when it is inactive, rather than an empty list.

## Alternatives considered

- **Everything project-scoped:** isolated, but repeated registration, polling, credentials and stored pull requests.
- **Secrets with several `project_id`s**, or an admin-only secrets table beside a project one: covers shared secrets but leaves repositories and datasets duplicated.
- **A `disabled_reason` string** instead of `revoked`: there is one reason.
- **A flat compatibility API** that hides the link (the link id as `id`): it would need the link id translated to the resource id in every client.
- **A composite foreign key from `projects.default_dataset_id` to the project's dataset link:** not used; the check is made when the default is resolved.

## Open questions

- Whether `whitelisted_images` should follow the same pattern.
- Dataset `PATCH` returns 200 and `/tasks` clamps `page` and `per_page` below 1 to 1; both are unconfirmed choices.
- A task that needs a dataset whose link is inactive fails at launch; whether it should wait instead.
- The cross-project loop check keys on `(provider_id, repo_path)`, so the same server under two host names is not seen.
