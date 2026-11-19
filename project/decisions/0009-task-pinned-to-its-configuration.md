# 0009. A task is pinned to its configuration

## Context

Global resources are shared and editable ([0006](0006-global-resources-and-project-resources.md)): a controller can change a dataset's host or a results repository's path while projects have tasks in flight. A task must neither run nor publish against a setup different from the one it was created for, and the record of what produced a result must stay.

## Decision

When a task is created it stores a snapshot (JSON, version 1) of the configuration it was built against and a sha256 hash of it (`tasks.config_snapshot`, `tasks.config_hash`). The snapshot holds:

- the results repository: its id, uri, the provider's `api_uri` and the project resource's `target_dir`;
- the task's dataset: name, host, port, type, read and write schema.

It does not hold credentials or secrets (a rotation must reach running work), the trigger repository (the task is pinned to the pull request's merge sha) or the `enabled` and `revoked` flags (those have their own rules, [0008](0008-enabled-revoked-and-soft-delete.md)). The snapshot is the audit record of what produced a result.

**Checks.** nexus-api rebuilds the snapshot from the current state and compares it (`helpers/task_config.py`). Only keys present in the stored snapshot are compared, so a field added later, or a task without a snapshot, counts as unchanged.

- *Before launch:* the Dagster launcher calls `POST /projects/<pid>/tasks/<id>/launch`, whose decision includes the pinned configuration (`GET .../config` shows `current`, `changes`, `config_hash`, `config_snapshot`). A task that is not current is not launched: nexus-api sets it to `FAILED` with the changes as `state_cause`, and the launcher carries on with the next task. An error while checking one task leaves it `PENDING` for the next tick and never stops the others; only the rules fail a task.
- *Before publishing:* `POST /projects/<pid>/results` for a `SUCCESS` task whose configuration changed creates the result as step `STALE`, state `FAILED`, with an error listing the changes. `STALE` is final, a sibling of `MERGED`, `CLOSED` and `REVOKED`: nothing is delivered.
- *At delivery,* the results repository id and `target_dir` come from the snapshot, so a deleted or edited project resource does not redirect the push.

**Edits are free.** A results resource's `target_dir`, a project resource swap, dataset resource edits, a trigger resource's `watch_dir` and `base_branch`, a repository's provider, path, `api_uri` and secret, global dataset fields and other project fields can be edited at any time. Assigning a project's results repository needs the project disabled.

## Consequences

- In-flight work is lost when a material field is edited: the task fails or its result is `STALE`. There is no stale-task retry: a stale task fails and the pull request has to be re-run another way.
- Dataset and results edits need no coordination with work in flight, and no drain.
- The disabled-project gap described in [0008](0008-enabled-revoked-and-soft-delete.md) is harmless for edits: a task created in the gap carries the old snapshot and fails, or its delivery gets a `REVOKED` result.


## Alternatives considered

- **Refuse edits while work is in flight** (drain guards on every edit): about 25 guard calls and a state to maintain, and they block the controller.
- **Pin the whole resource row:** would pin credentials and flags, which must be live.

## Open questions

- `config_hash` is stored and returned but never compared; the comparison uses the snapshot itself.
