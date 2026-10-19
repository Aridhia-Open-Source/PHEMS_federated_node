"""
The configuration a task is pinned to. When a task is created a small snapshot of what decides
where its results go and which data it reads is stored on it, with a hash. Before the task
launches and before its results are published the snapshot is rebuilt from the current state
and compared: a task whose setup changed fails and is never run or published against the new one.

Not in the snapshot: credentials and secrets (a rotation has to reach running work), the trigger
repository (the task is pinned to the pull request's merge sha) and the enabled and revoked flags
(those have their own rules). One of those is shared: a task whose project, or a trigger, dataset or
results repository it uses (the project's link, the global resource, a repository's provider) is revoked or
deleted (see revoked_resources) does not launch and its results are never delivered.
"""
import hashlib
import json

from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.pull_request_trigger import PullRequestTrigger

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


def results_link(project_id: int, results_repository_id: int | None = None) -> ProjectResultsRepository | None:
    """
    The project's link to the results repository, a deleted one too (it is revoked, so its delivery gets
    the final REVOKED result), the newest if there are several. Without a repository id, the project's
    newest link to any.
    """
    query = ProjectResultsRepository.query.filter_by(project_id=project_id)
    if results_repository_id is not None:
        query = query.filter_by(results_repository_id=results_repository_id)
    return query.execution_options(include_deleted=True).order_by(ProjectResultsRepository.id.desc()).first()


def revoked_resources(task, results_repository_id: int | None = None) -> list[str]:
    """
    What the task uses that is revoked or deleted; empty when nothing is. A task with a revoked resource does
    not launch and its results are never delivered. Switched off is not revoked. Each is named once:
    - the project the task is in: "project p (revoked)";
    - the pull request trigger's repository: its project link, "trigger repository o/r", the global repository
      and its provider, "trigger repository o/r (revoked)", "provider git (revoked)";
    - the dataset: its project link, "dataset ds" (also when the project has none), the global dataset,
      "dataset ds (revoked)";
    - the results repository, like the trigger one. Its link is to the given repository, else the one the
      task was pinned to, else the project's newest.
    """
    revoked = []

    def add(name: str):
        if name not in revoked:
            revoked.append(name)

    def add_repository(kind: str, link, repository):
        if link.revoked:
            add(f"{kind} {repository.repo_path}")
        if repository.revoked:
            add(f"{kind} {repository.repo_path} (revoked)")
        if repository.provider.revoked:
            add(f"provider {repository.provider.name} (revoked)")

    if task.project.revoked:
        add(f"project {task.project.name} (revoked)")
    if isinstance(task.trigger, PullRequestTrigger):
        link = task.trigger.project_trigger_repository
        add_repository("trigger repository", link, link.trigger_repository)
    if task.spec.dataset_id:
        link = ProjectDataset.query.filter_by(
            project_id=task.project_id, dataset_id=task.spec.dataset_id
        ).execution_options(include_deleted=True).order_by(ProjectDataset.id.desc()).first()
        if link is None or link.revoked:
            add(f"dataset {task.spec.dataset.name}")
        if task.spec.dataset.revoked:
            add(f"dataset {task.spec.dataset.name} (revoked)")
    if results_repository_id is None and task.config_snapshot and task.config_snapshot["results"]:
        results_repository_id = task.config_snapshot["results"]["repository_id"]
    link = results_link(task.project_id, results_repository_id)
    if link is not None:
        add_repository("results repository", link, link.results_repository)
    return revoked
