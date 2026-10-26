# 0008. Enabled, revoked and soft delete

## Context

Access to a global resource ([0006](0006-global-resources-and-project-resources.md)) has to be switched off temporarily by a person, and withdrawn by the controller, without breaking work that is already in flight or losing the record of what produced a result. Waiting (a project off, a delivery that cannot proceed) should cost nothing.

## Decision

### Two flags

- `enabled`: a person turned the project or resource on or off. It stops new work; work in flight finishes, and waiting work resumes when it is switched back on.
- `revoked`: the controller withdrew access. It blocks the work: a task that uses a revoked resource does not launch, and its result is never delivered.

Revoking sets only `revoked`, never `enabled`, so a re-grant clears `revoked` and restores the previous state without overriding a manual disable. Revoking affects only that resource; the rest of the project keeps running, and the project health check reports it. Revoke takes effect immediately and is not blocked by work in flight. Only administrators set `revoked`, on every route that has it; the pipeline's System user can never revoke or un-revoke.

Both flags exist at two levels. A global resource (dataset, trigger repository, results repository, git provider) has its own `enabled` and `revoked`; a secret has `enabled` only. A project has them, and so has each project resource. A project resource is **active** when its global resource (and, for a repository, its provider) and the project resource are enabled and not revoked. A project resource accepts triggers only if its project is also enabled and not revoked. Global flags are read live. "Active" is the usable-now test, which the webserver applies when it decides a launch ([0021](0021-webserver-owns-the-record-and-the-rules.md)); the blocked test (`revoked_resources`) looks only at `revoked` and `deleted_at`. The full tables, what each state does to each kind of work, and the flows are in [revoke-and-enabled.md](../../docs/architecture/revoke-and-enabled.md).

### What switching off and revoking do

Switching off stops new work and work in flight finishes once it is back on. Revoking stops all work for good.

| Switched off | New pull requests | A task not launched yet | A finished task's results |
|---|---|---|---|
| Trigger resource, trigger repository or its provider | Stored, no trigger; the project resource's cursor moves to now when it is on again ([0011](0011-pull-requests-stored-once-fan-out-and-cursors.md)) | Launches | Delivered |
| Project | Stored, no trigger; no task from a pull request or the API (409) | Waits: the launcher skips a disabled project | Delivered |
| Results resource, results repository or its provider | n/a | Launches | Result `FAILED` ("results resource switched off"), retried by the delivery retry sensor once the project resource is active again |
| Dataset resource or global dataset | n/a | `FAILED` at launch, naming the dataset | n/a |
| **Revoked** (any project resource) | Trigger resource: no trigger, and its triggers get no task (409). Project: no trigger, and no task from a pull request or the API (409) | Dataset resource: `FAILED` at launch | Results resource: result `REVOKED`, final, never delivered |

- A secret's credentials are outside the task's pinned configuration; disabling a secret disables what uses it ([0007](0007-secrets-and-secret-providers.md)).
- A `FAILED` result for a switched-off project resource is not final. `results_delivery_retry_sensor` lists `FAILED` results whose project resource is active (`GET /projects/<pid>/results?state=FAILED&active_resource=true`) and launches their delivery, which reads the task run's artifacts. Artifact clean-up must wait for delivery, not for the task's end.
- `REJECTED` is final for a trigger: no request moves it back ([0005](0005-state-transition-tables.md)).
- A project has one flag, `enabled`, and no lock. A new project is disabled, so its results repository is assigned before it is enabled. A disabled or revoked project gets no new triggers, and a task is refused (409) whether it comes from a pull request or from the API; one shared check (`require_accepts_tasks`) applies both. A trigger that exists when its project is disabled stays `UNKNOWN` and gets its task once the project is enabled and not revoked. A disabled project's `PENDING` tasks wait. Enabling it skips the gap by default; `"backfill": true` creates the missed triggers instead.
- A delivery already past the results check, and a running task, are not stopped by a revoke.
- The check that a project accepts tasks and the task insert are separate steps, so a task can be created just as the project is disabled. This follows from the event-driven design ([0021](0021-webserver-owns-the-record-and-the-rules.md)): at worst the task runs against a setup that has just changed and fails or is not delivered, nothing is lost and other projects are unaffected.

### Soft delete

- `deleted_at` (nullable) is on projects, the four project resource tables and the global resources (trigger and results repositories, datasets, secrets, git providers). Deleting sets it and, on every row with the flag, `revoked`, so a deleted resource blocks like a revoked one.
- One `do_orm_execute` listener (`helpers/soft_delete.py`) hides deleted rows from every ORM query unless the query sets `include_deleted`. For the API a deleted row is gone (404, not listed), with no admin back door. Many-to-one references (`task.project`, `result.assignment`) still load a deleted row, so history never meets `None`; collections and queries hide it.
- Unique names, labels, the id pairs of the project resource tables and `(provider_id, repo_path)` are partial unique indexes `WHERE deleted_at IS NULL`, so a deleted name is free again.
- Deleting a project resource revokes it. Deleting a dataset or repository with live project resources is a 409 listing the projects, unless `?force=true`, which revokes and deletes every project resource. Deleting a project soft deletes it and all its project resources. A secret goes with its project resources and its stored value is deleted from the store. A git provider is refused while a repository is on it.
- **Delivery of a deleted project resource.** `POST /projects/<pid>/results` is the only gate: it reads the project resource with `include_deleted`, and a revoked project resource, a deleted one included, gives the existing final `REVOKED` result. Delivery takes `target_dir` and the repository id from the task's pinned configuration and the repository, provider and secret from `GET /global/repositories/results/<id>`. A 404 (project, task or repository) is final: logged, no retry.
- Everything that decides whether a result is created, and in which step, is in `POST /projects/<pid>/results`, checked in order: the result exists (final steps are returned as they are, others are re-checked for a revoke), the task is `SUCCESS` (else 409), something the task uses is revoked or deleted (`REVOKED`), the configuration changed (`STALE`), a project resource switched off (`FAILED`, held). A task created while a project resource was being revoked is caught here, not at creation.

### Who owns what

The webserver owns the business record, the rules, audit and compliance; Dagster holds operational history (runs). Dagster calls the webserver's API. The webserver also has `/dagster/sensors` routes that call Dagster, kept as an operational convenience. The pipeline stays event driven: sensors react to the webserver's state, so waiting costs nothing.

## Consequences

- A person's switch and the controller's withdrawal never overwrite each other.
- Work in flight is not killed: a revoke or a delete stops launching and delivering, and a push that has begun may still complete once. A leaked git token must also be revoked at the git host.
- A project that is both revoked and disabled keeps its waiting tasks waiting, because the launcher reads enabled projects only; they fail once it is enabled.
- A result recorded before a revoke keeps its step until `POST /projects/<pid>/results` is called for it again, which each delivery attempt does first.
- A backfill exists only when a project is enabled, not for a project resource, repository or provider being switched back on.

## Alternatives considered

- **A `disabled_reason` string:** there is one reason, so a boolean.
- **A project lock besides `enabled`:** one flag with an optional backfill at enable does the same job.
- **Draining in-flight work before an edit, an enable flip or a delete:** pinning a task to its configuration ([0009](0009-task-pinned-to-its-configuration.md)) and soft delete make every edit free.
- **Hard delete:** history and results must still resolve their project resources.

## Open questions

- `ProjectSecret` has the flags but nothing reads them.
- A delivery that stays `FAILED` after the maximum attempts raises no alert ([0015](0015-run-keys-retries-and-results-pr-sync.md)).
- A project resource's `active` ignores its secret; only the `pollable` filter uses the secret's flags.
