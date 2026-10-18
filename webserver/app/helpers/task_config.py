"""
The configuration a task is pinned to. When a task is created a small snapshot of what decides
where its results go and which data it reads is stored on it, with a hash. Before the task
launches and before its results are published the snapshot is rebuilt from the current state
and compared: a task whose setup changed fails and is never run or published against the new one.

Not in the snapshot: credentials and secrets (a rotation has to reach running work), the trigger
repository (the task is pinned to the pull request's merge sha) and the enabled and revoked flags
(those have their own rules).
"""
import hashlib
import json

SNAPSHOT_VERSION = 1


def build_snapshot(project, dataset) -> dict:
    """
    The snapshot of the configuration a task of the project, running on the dataset (or none), is
    built against. The project has at most one results link.
    """
    link = project.get_results_repository()
    results = None
    if link is not None:
        repository = link.results_repository
        results = {
            "repository_id": repository.id,
            "repository": repository.uri,
            "api_uri": repository.provider.api_uri,
            "target_dir": link.target_dir,
        }
    return {
        "version": SNAPSHOT_VERSION,
        "results": results,
        "dataset": None if dataset is None else {
            "name": dataset.name,
            "host": dataset.host,
            "port": dataset.port,
            "type": dataset.type,
            "read_schema": dataset.read_schema,
            "write_schema": dataset.write_schema,
        },
    }


def snapshot_hash(snapshot: dict) -> str:
    """sha256 hex of the snapshot's canonical JSON."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _diff_value(path: str, stored, current, changes: list[str]):
    if isinstance(stored, dict) and isinstance(current, dict):
        # Only what the stored snapshot has is compared: a field added later is unchanged
        for key in stored:
            _diff_value(f"{path}.{key}", stored[key], current.get(key), changes)
    elif stored != current:
        changes.append(f"{path}: {stored!r} -> {current!r}")


def diff(stored: dict, current: dict) -> list[str]:
    """
    Human-readable lines for what differs, e.g. "results.target_dir: 'results/' -> 'out/'". Only
    keys present in the stored snapshot are compared, and a differing version is not a change.
    """
    changes: list[str] = []
    for key in stored:
        if key == "version":
            continue
        _diff_value(key, stored[key], current.get(key), changes)
    return changes


def current_snapshot(task) -> dict:
    """The snapshot of the task's configuration as it is now."""
    return build_snapshot(task.project, task.spec.dataset)


def config_changes(task) -> list[str]:
    """What changed in the task's configuration since it was created. Empty when it has no snapshot."""
    if not task.config_snapshot:
        return []
    return diff(task.config_snapshot, current_snapshot(task))
