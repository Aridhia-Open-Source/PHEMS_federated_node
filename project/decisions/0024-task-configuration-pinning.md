# 0024. A task is pinned to its configuration

- Status: Accepted (built)
- Part of the split of [0019](0019-global-resources-and-shared-pull-requests.md). Related: [0021](0021-global-resources-and-project-links.md) (global resources and links), [0025](0025-switching-off-revoking-and-soft-delete.md) (off, revoked, deleted), [0026](0026-state-transition-tables.md).

## Context

- A global dataset, repository or provider is shared by many projects, and editing it changes the setup of every task that uses it.
- Before this, an edit needed the project locked and drained (no task in flight), so every edit route called a guard. That blocks the data controller whenever any task is running, and it still had a race: a task created between the guard and the edit.
- What matters is not that nothing is in flight, but that a task is never run or published against a setup other than the one it was created under.

## Decision

- **Snapshot at creation.** `NewTaskDTO.from_spec` (`webserver/app/dtos/task.py`) calls `build_snapshot(project, dataset)` and stores the result in `tasks.config_snapshot` (JSON) and its sha256 in `tasks.config_hash` (`models/task.py`, `001_baseline.py`). `snapshot_hash` hashes canonical JSON (sorted keys, no spaces).
- **What is in it** (`webserver/app/helpers/task_config.py`, `SNAPSHOT_VERSION = 1`):
  - `results`: the results repository's id and uri, the provider's `api_uri`, and the link's `target_dir`. `None` when the project has no results link.
  - `dataset`: name, host, port, type, `read_schema`, `write_schema`. `None` when the task has no dataset.
- **What is not in it:** credentials and secrets (a rotation has to reach running work), the trigger repository (the task is pinned to the pull request's merge sha), `enabled` and `revoked` (they have their own rules, [0025](0025-switching-off-revoking-and-soft-delete.md)).
- **The check.** `config_changes(task)` rebuilds the snapshot from current state (`task.project`, `task.spec.dataset`) and `diff`s it with the stored one, giving lines like `results.target_dir: 'results/' -> 'out/'`.
  - Only keys present in the stored snapshot are compared; a field added later is unchanged. A differing `version` is not a change.
  - A task with no snapshot (`config_snapshot` empty) has no changes.
  - Deleting the results link makes `results` become `None`, which counts as a change (the project's link collection hides deleted rows).
- **Endpoint.** `GET /projects/<pid>/tasks/<id>/config` (`tasks_api.get_task_config`) returns `{"current", "changes", "config_hash", "config_snapshot"}`.
- **Launch gate.** `TaskLauncherSensor._launch` (`dagster/app/definitions/sensors/task/launcher.py`) calls it first for each PENDING task of an enabled project. If not current, it patches the task to `FAILED` with `state_cause` = "task configuration changed since the task was created: ..." (cut to 1024) and returns no run; the loop carries on with the next task. Any other error (for example the config GET failing) is logged and the task stays PENDING for the next tick.
- **Publish gate.** `POST /projects/<pid>/results` (`results_api.post_result`) runs its checks in this order: existing result (returned, 200), task is `SUCCESS` (else 409), link revoked (`REVOKED`), configuration changed (`STALE`), link switched off (`FAILED` at step `UNKNOWN`, "results link switched off"). A stale task gets a result created at step `STALE`, state `FAILED`, error listing the changes (cut to 1024), 201. `STALE` is final: it ranks with `MERGED`, `CLOSED` and `REVOKED` in `RESULT_ORDER` (`models/pull_request_result_step.py`), and the retry sensor and `FINAL` in `dagster/app/delivery/results.py` skip it. Nothing is delivered.
- **Delivery takes its target from the snapshot.** `ResultsDelivery.__call__` reads `get_task_config(...)["config_snapshot"]["results"]`, calls `create_result` with `results["repository_id"]`, and pushes into `results["target_dir"]`. The repository itself, its provider and its secret are read live from `GET /global/repositories/results/<id>`. So the snapshot's `repository`, `api_uri` are only compared, not used to deliver, and a deleted link does not stop delivery from knowing where to go.
- **No retry for a stale task in the beta.** `POST .../retry` resets a `FAILED` task to `PENDING`, but the launcher rebuilds the check and fails it again; the pull request has to be re-run another way.
- **Edits need no guard.** A results link's `target_dir`, a link swap, a dataset's fields, a provider's fields, a trigger link's `watch_dir` and `base_branch` are all free. The only remaining use of the lock for configuration is creating a project's results link (`helpers/project_lock.py`, `require_locked`, called in `projects_api.py`).

## Consequences

- The data controller can edit a shared resource at any time; no drain, no lock, no "who is running" question.
- In-flight work is lost when a material field is edited: a PENDING task is failed at launch, and a finished task's result is `STALE`. A task already running is not stopped; its result is then `STALE` at publish.
- The snapshot is an audit record of what produced a result, and the diff text says what changed.
- A stale task is a real failure the person sees (`state_cause`, result error), not a silent wrong delivery.
- The check is one extra GET per PENDING task per sensor tick, and a rebuild per `POST /results`.
- The snapshot is rebuilt from rows, so the check is only as strong as its field list: a field outside the snapshot can change under a running task. That is deliberate for credentials and trigger repository.

## Alternatives considered

- **Hash only.** Smaller, but says nothing about what changed and cannot hold the delivery target; the diff and `config_snapshot` come from keeping the document.
- **Version counters on each resource.** Every edit bumps a counter, and the task stores the counters. Counts edits that change nothing material (a description) and needs a counter on every table in the chain; fails tasks more often.
- **Optimistic concurrency on the edit** (refuse an edit while a task depends on it). Brings back the drain in another form, and the controller cannot change a shared resource while any project is running.
- **Snapshot and use the copy** (run and deliver entirely from the snapshot). Would also pin the repository, provider and credentials, so a rotation or a moved repository would not reach running work, and a copied token is a secret at rest. Only `repository_id` and `target_dir` are used from the snapshot.
- **Keep lock and drain** (the old rule): rejected, see Context.

## Where it lives

- PR #556 (webserver, branch `split/02-webserver`): `webserver/app/helpers/task_config.py`, `dtos/task.py`, `models/task.py`, `tasks_api.py` (`get_task_config`), `results_api.py` (`post_result`), `models/pull_request_result_step.py`, `migrations/versions/001_baseline.py` (`tasks.config_snapshot`, `tasks.config_hash`).
- PR #557 (Dagster launcher and delivery, branch `split/03-dagster`): `dagster/app/definitions/sensors/task/launcher.py`, `dagster/app/delivery/results.py`, `dagster/app/backend.py` (`get_task_config`).

## Not built or open

- No retry or re-run path for a stale task.
- No stop for a task already running when its configuration changes; it finishes and is then `STALE`.
- `config_hash` is stored and returned but nothing compares it; the check diffs the documents. It is for audit.
- The snapshot's `repository` uri and `api_uri` are compared but not used to deliver; delivery reads the live repository by id.
- `SNAPSHOT_VERSION` has no migration path: a version change is ignored in the diff, so a new field is simply not checked on old tasks.
- `webserver/app/models/project.py` still has a comment saying the lock lets "what is in flight drain"; stale, not yet corrected.
