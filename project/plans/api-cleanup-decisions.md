# Plan: API cleanup onto fednode (do at the end, then propagate up)

PR #806 `refactor/api-onto-fednode` (T-143), between #696 and #766. #696 stays as reviewed.

## Rule
- Standalone code that talks to an outside API (git, Kubernetes, Keycloak) goes in fednode's client for it, whoever uses it. API-specific logic around it (caching in the API's secrets, permission checks) stays in the API.

## In #806
- Done: deleted the leftover `app/helpers/*` copies and the API's `repos/git_uri` (now `fednode.clients.git.uri`).
- Agent: git token minting into the fednode git clients (GitProvider.mint_token + the factory Dagster uses); the API only reads the repo's credentials and asks the client.
- Renames in `nexus/api/app/tasks/`:
  - `task_config` -> `config`
  - `task_resources` -> `resources`
  - `spec_files` -> `specs`

- Task config snapshot (`tasks/task_config`) becomes methods on the Task model (`task.snapshot()`, `task.config_changes()`).
- `tasks/compute` + `tasks/limits` become validators on a shared `TaskCompute` model in fednode (`fednode/clients/nexus/models/task_compute.py`, renamed from `TaskResources`). The API's create-task request takes `compute: TaskCompute` (API change: clients send `compute`, not `resources`); Dagster gets the same class through the nexus client.
- Task limits: the API's `TaskLimitsSettings` becomes `TaskComputeLimits` in `fednode/settings.py` (all optional; the API's subclass makes them required). `TaskCompute` checks format always, and checks against limits only when given them as Pydantic validation context: the API does `TaskCompute.model_validate(body, context={"limits": settings.tasks.limits})`, Dagster validates without context.
- `tasks/task_resources` becomes a run-inputs class (a run's Secret + ConfigMap: `create()`, classmethod `delete(run_id)`) beside the API's Kubernetes wrapper in `app/clients/`; built by the route, not the model. Name: `RunResources` (made per run, matches the `/tasks/<id>/runs/<run_id>/resources` route; runs stay a concept, retries are coming). Keep the route as is.
- Delete the stale copies `tasks/resources.py` (or `task_resources.py`, whichever the routes don't import) and `app/tasks_api.py` (twin of `app/projects/tasks_api.py`; check which is mounted).
- Exceptions: `KeycloakError`, `KubernetesException` (rename `KubernetesError`) and `GitProviderError` move to fednode as subclasses of `fednode.http.ClientError` (GitProviderError already replaced by ClientError in #806); the API's ClientError handler (502) covers them. `InvalidRequest`, `AuthenticationError`, `UnauthorizedError`, the DB errors, `TaskImageException`, `NotImplementedException` stay in the API.
- Delete `app/clients/kubernetes.py` and `app/clients/kubernetes_names.py` (they only translate errors): the API uses fednode's Kubernetes client and name checks directly; nexus-api's FastAPI error handlers map fednode's Kubernetes errors (ClientError subclass, 502) and the name-check errors (422).
- Error codes follow the HTTP spec: invalid values (request validation, name checks) are 422, FastAPI's default; 400 only for requests that can't be read (broken JSON). Change `errors.py`'s validation handler from 400 to 422 and update the tests that expect 400. API change, beta.
- `tasks/spec_files` becomes a method on the project's trigger repository model (it owns `watch_dir`): `project_trigger_repository.spec_files(pull_request)`, with `is_under_dir` beside it. Callers: models/pull_request_trigger.py, repos/pull_request_fanout.py. `tasks/` is then empty: delete it.

- `repos/repository_loop` becomes `Project.check_results_dir_not_watched()` on the Project model: for each of the project's trigger repositories that is the same git repo as its one results repository, the trigger's watch_dir must not overlap the results target_dir (either inside the other; '' = whole repo). Per project only: no cross-project check (chaining projects is allowed). Called when a project's trigger or results repository is added or changed. Path helpers (`normalise_dir`, segments/overlap, `is_under_dir`) sit together.
- `repos/pull_request_fanout` (DB only, no git calls) becomes model methods; the file goes. Cross-model references through the `models` ModelRegistry (`models/__init__.py`) to avoid import cycles.
  - `store_pull_request` -> `PullRequest.store(...)` (classmethod)
  - `ingest_pull_requests` -> `TriggerRepository.ingest(requests)` (stores, then fans out; `fan_out` folds into it)
  - `active_assignments` -> `TriggerRepository.active_assignments` (property)
  - `create_triggers` -> `ProjectTriggerRepository.create_triggers(pull_request_ids=None)`
  - `unmatched_cause` -> `ProjectTriggerRepository.unmatched_cause(pull_request)`
  - `backfill` -> `ProjectTriggerRepository.backfill()`; `skip_gap` -> `ProjectTriggerRepository.skip_gap()`
  - Routes call `repo.ingest(...)`, `assignment.backfill()`, `assignment.skip_gap()`.
- `repos/git_tokens`: `mint_token` (read the repo's secret, reuse a cached token, else mint via fednode's git factory and cache it back) stays in the API, as `app/helpers/git.py`. `require_token_allowed` becomes a method on the repository model (pure checks; the project part on the project's link to the repo). `repos/` is then empty: delete it.

## In #686
- Agent: `AccessTokenVerifier` (clients/access_token.py) into `fednode.clients.keycloak.keys`.

## When propagating up the chain (#766 onto #806, then every stack above)
- `app/helpers/ownership.py`, `app/helpers/task_config.py` stay deleted; move any upper-PR edits to `app/rules/ownership.py` / `app/tasks/config.py`.
- `app/tasks/resources.py` (old copy added above fednode): delete in the PR that adds it, imports to the renamed `tasks/resources`.
- Apply the tasks/ renames to any upper-PR imports.
- New commit per PR with a line in its `.github/ci-retrigger/pr-N.md`; never reuse old commit messages ([skip ci]).

## Middleware
- Remove `JsonObjectBodyMiddleware` (middleware.py): routes take Pydantic request models instead of indexing the raw body, so FastAPI refuses non-object bodies (422). Convert any route still reading the raw body first. `SessionMiddleware` and `TrailingSlashMiddleware` stay.
- `errors.py` stays (gains the handlers above).

## Dead router copies (auth stack)
- 10 router files at `nexus/api/app/` top level are dead copies of the mounted ones in `globals/` and `projects/`: datasets_api, git_providers_api, results_repositories_api, secrets_api, trigger_repositories_api, users_api, project_trigger_repositories_api, projects_api, results_api, tasks_api. Nothing imports them (one test may import the old tasks_api).
- They came back in the auth stack's "restore ... the rebuild dropped" commits (e.g. a2b1263da owner group removal, 40797d2c2 Keycloak token verification), which restored auth edits into the old flat files.
- Before deleting: diff each dead copy's auth edits against the live router and carry anything missing across. Delete in the auth PR that brought them back.

## Later
- Slim `app/clients/keycloak.py` onto fednode's `KeycloakAdmin` (after the auth stack; it rewrites that file).

## Decided
- #806: token type picked by provider type; a secret whose keys do not match its provider is a 409 (codepint OK, 2026-11-27).
