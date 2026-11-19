"""
The difference between a node file and what the backend holds (`fncli diff`), with no I/O so it can be tested on its
own: a snapshot of the backend as plain dataclasses in, a list of changes out.

Everything is compared in its normalised form (repository and provider uris, directories, lowercase dataset names), or
the plan would show differences that are not there. Identity decides create or update: a repository is its uri, a
provider its uri, a secret its label, a dataset its name, a project its name. A secret is only ever "missing" or
"exists": the backend returns no values, so they cannot be compared. Nothing in the backend that the file does not
list is touched, so the plan has no deletions.

A file may name what it does not hold: a project's dataset or repository, a repository's or dataset's secret. That is
resolved here, against the backend. What is on the node shows as an existing reference (unchanged, "on the node, not in
this file"); what is neither in the file nor on the node blocks the row that names it, so nothing half-made is applied.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from fncli.backend import repo_path_of
from fncli.nodefile.schema import NodeFile, ProjectSpec, SecretSpec, normalise_dir

CREATE, UPDATE, UNCHANGED, CONFIRM, BLOCKED, ENSURE = "create", "update", "unchanged", "confirm", "blocked", "ensure"
EARLIER_TASKS_FAIL = "earlier tasks will fail"
NOT_FOUND = "is not in the file or on the node"
REFERENCE = "on the node, not in this file"
NONE = "(none)"
# What nexus-api pins into every task when it is created (nexus/api/app/helpers/task_config.py)
PINNED_DATASET_FIELDS = ("type", "host", "port", "read_schema", "write_schema")


@dataclass(frozen=True)
class ProviderState:
    name: str
    type: str
    uri: str  # normalised
    api_uri: str


@dataclass(frozen=True)
class RepositoryState:
    uri: str  # normalised
    provider: str  # the provider's uri
    secret: str  # the secret's label


@dataclass(frozen=True)
class DatasetState:
    name: str
    type: str
    host: str
    port: int
    read_schema: str | None
    write_schema: str | None
    secret: str


@dataclass(frozen=True)
class TriggerState:
    repository: str  # normalised uri
    watch_dir: str
    base_branch: str
    enabled: bool


@dataclass(frozen=True)
class ResultsState:
    repository: str  # normalised uri
    target_dir: str
    base_branch: str
    enabled: bool


@dataclass(frozen=True)
class ProjectState:
    name: str
    enabled: bool
    datasets: list[str]  # names of the assigned datasets, inactive ones included
    default_dataset: str | None
    triggers: list[TriggerState]
    results: ResultsState | None  # a project has at most one


@dataclass(frozen=True)
class BackendState:
    providers: list[ProviderState]
    secrets: set[str]  # labels
    trigger_repositories: list[RepositoryState]
    results_repositories: list[RepositoryState]
    datasets: list[DatasetState]
    projects: list[ProjectState]


@dataclass(frozen=True)
class FieldChange:
    field: str
    old: str | None  # None for an assignment that is new
    new: str

    def __str__(self):
        return f"{self.field}: + {self.new}" if self.old is None else f"{self.field}: {self.old} -> {self.new}"


@dataclass(frozen=True)
class Change:
    """
    One line of the plan. kind and name say what it is, detail and fields what happens, warnings what it
    disrupts, and also_used_by the projects outside the file that are assigned a global resource that changes.
    key is what identifies it in the file (a repository's or provider's normalised uri, else the name), which
    apply looks the file's entry up by: a repository's name is only its owner/repo, the same on two providers.
    """

    action: str
    kind: str
    name: str
    detail: str = ""
    fields: tuple[FieldChange, ...] = ()
    warnings: tuple[str, ...] = ()
    also_used_by: tuple[str, ...] = ()
    key: str = ""


def shown(value) -> str:
    if value is None or value == "":
        return NONE
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def compare(field: str, old, new, same: Callable = lambda a, b: a == b) -> FieldChange | None:
    """The change from old to new, or None when they are the same. An unset value and an empty one are the same."""
    old, new = (None if value == "" else value for value in (old, new))
    if old is None or new is None:
        return None if old is new else FieldChange(field, shown(old), shown(new))
    return None if same(old, new) else FieldChange(field, shown(old), shown(new))


def same_dir(a: str, b: str) -> bool:
    return normalise_dir(a) == normalise_dir(b)


def same_uri(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


def found(changes: list[FieldChange | None]) -> tuple[FieldChange, ...]:
    return tuple(change for change in changes if change)


def users(node: NodeFile, state: BackendState, uses: Callable[[ProjectState], bool]) -> tuple[str, ...]:
    """The projects of the backend, outside the node file, that a global resource is assigned to"""
    in_file = {project.name for project in node.projects}
    return tuple(sorted(p.name for p in state.projects if p.name not in in_file and uses(p)))


def describe_secret(spec: SecretSpec) -> str:
    if spec.gitea_oauth:
        return f"gitea OAuth app {spec.gitea_oauth.app}"
    return f"values {', '.join(spec.values)}"


def gitea_changes(node: NodeFile) -> list[Change]:
    """Gitea is not read, so a repository there is only said to be created if it is missing"""
    if node.gitea is None or not node.gitea.create_repositories:
        return []
    uris = dict.fromkeys(repo.uri for repo in node.repositories.triggers + node.repositories.results)
    return [
        Change(ENSURE, "gitea repo", repo_path_of(uri), "created at apply if missing", key=uri)
        for uri in uris
        if node.provider_for(uri).resolved_name == node.gitea.provider
    ]


def has_secret(node: NodeFile, state: BackendState, label: str) -> bool:
    return label in node.secrets or label in state.secrets


def references(node: NodeFile, state: BackendState) -> dict[str, dict[str, str]]:
    """
    What the file names without holding it, and the node has: kind -> {key: name as the node spells it}. A dataset's
    key is its lowercase name, a repository's its normalised uri, a secret's its label.
    """
    in_file = {
        "dataset": {dataset.name.lower() for dataset in node.datasets},
        "trigger": {repo.uri for repo in node.repositories.triggers},
        "results": {repo.uri for repo in node.repositories.results},
    }
    on_node = {
        "dataset": {dataset.name.lower(): dataset.name for dataset in state.datasets},
        "trigger": {repo.uri: repo_path_of(repo.uri) for repo in state.trigger_repositories},
        "results": {repo.uri: repo_path_of(repo.uri) for repo in state.results_repositories},
    }
    named = {
        "dataset": [name.lower() for project in node.projects for name in project.datasets],
        "trigger": [t.repository for project in node.projects for t in project.repositories.triggers],
        "results": [project.repositories.results.repository for project in node.projects],
    }
    found = {
        kind: {key: on_node[kind][key] for key in dict.fromkeys(keys) if key not in in_file[kind] and key in on_node[kind]}
        for kind, keys in named.items()
    }
    labels = [repo.secret for repo in node.repositories.triggers + node.repositories.results]
    labels += [dataset.secret for dataset in node.datasets]
    found["secret"] = {label: label for label in dict.fromkeys(labels) if label not in node.secrets and label in state.secrets}
    return found


def secret_changes(node: NodeFile, state: BackendState) -> list[Change]:
    return [
        Change(UNCHANGED, "secret", label, "exists, values not compared", key=label) if label in state.secrets
        else Change(CREATE, "secret", label, describe_secret(spec), key=label)
        for label, spec in node.secrets.items()
    ] + [
        Change(UNCHANGED, "secret", label, REFERENCE, key=label) for label in references(node, state)["secret"]
    ]


def provider_changes(node: NodeFile, state: BackendState) -> list[Change]:
    existing = {provider.uri: provider for provider in state.providers}
    changes = []
    for spec in node.providers:
        current = existing.get(spec.uri)
        if current is None:
            changes.append(Change(CREATE, "provider", spec.resolved_name, f"{spec.type}, api {spec.api_uri}", key=spec.uri))
            continue
        fields = found([
            compare("name", current.name, spec.name) if spec.name else None,
            compare("type", current.type, spec.type),
            compare("api_uri", current.api_uri, spec.api_uri, same_uri),
        ])
        if not fields:
            changes.append(Change(UNCHANGED, "provider", spec.resolved_name, key=spec.uri))
            continue
        on_provider = {r.uri for r in state.trigger_repositories + state.results_repositories if r.provider == spec.uri}
        used = users(
            node, state,
            lambda p: any(t.repository in on_provider for t in p.triggers)
            or (p.results is not None and p.results.repository in on_provider),
        )
        changes.append(Change(UPDATE, "provider", spec.resolved_name, fields=fields, also_used_by=used, key=spec.uri))
    return changes


def repository_changes(node: NodeFile, state: BackendState, kind: str) -> list[Change]:
    if kind == "trigger":
        specs, existing = node.repositories.triggers, state.trigger_repositories

        def uses(project, uri):
            return any(trigger.repository == uri for trigger in project.triggers)
    else:
        specs, existing = node.repositories.results, state.results_repositories

        def uses(project, uri):
            return project.results is not None and project.results.repository == uri

    current_by_uri = {repo.uri: repo for repo in existing}
    changes = []
    for spec in specs:
        name = repo_path_of(spec.uri)
        current = current_by_uri.get(spec.uri)
        if not has_secret(node, state, spec.secret):
            changes.append(Change(BLOCKED, f"{kind} repo", name, f"secret {spec.secret} {NOT_FOUND}", key=spec.uri))
            continue
        if current is None:
            changes.append(Change(CREATE, f"{kind} repo", name, f"secret {spec.secret}", key=spec.uri))
            continue
        fields = found([
            compare("secret", current.secret, spec.secret),
            compare("provider", current.provider, node.provider_for(spec.uri).uri),
        ])
        if fields:
            used = users(node, state, lambda p: uses(p, spec.uri))
            changes.append(Change(UPDATE, f"{kind} repo", name, fields=fields, also_used_by=used, key=spec.uri))
        else:
            changes.append(Change(UNCHANGED, f"{kind} repo", name, key=spec.uri))
    changes += [
        Change(UNCHANGED, f"{kind} repo", name, REFERENCE, key=uri) for uri, name in references(node, state)[kind].items()
    ]
    return changes


def dataset_changes(node: NodeFile, state: BackendState) -> list[Change]:
    existing = {dataset.name.lower(): dataset for dataset in state.datasets}
    changes = []
    for spec in node.datasets:
        current = existing.get(spec.name.lower())
        if not has_secret(node, state, spec.secret):
            changes.append(Change(BLOCKED, "dataset", spec.name, f"secret {spec.secret} {NOT_FOUND}", key=spec.name))
            continue
        if current is None:
            detail = f"{spec.type} {spec.host}:{spec.port}, secret {spec.secret}"
            changes.append(Change(CREATE, "dataset", spec.name, detail, key=spec.name))
            continue
        pinned = found([compare(name, getattr(current, name), getattr(spec, name)) for name in PINNED_DATASET_FIELDS])
        fields = pinned + found([compare("secret", current.secret, spec.secret)])
        if not fields:
            changes.append(Change(UNCHANGED, "dataset", spec.name, key=spec.name))
            continue
        used = users(node, state, lambda p: spec.name.lower() in {name.lower() for name in p.datasets})
        warnings = (EARLIER_TASKS_FAIL,) if pinned else ()
        changes.append(Change(UPDATE, "dataset", spec.name, fields=fields, warnings=warnings, also_used_by=used, key=spec.name))
    changes += [
        Change(UNCHANGED, "dataset", name, REFERENCE, key=key) for key, name in references(node, state)["dataset"].items()
    ]
    return changes


def create_project(spec: ProjectSpec) -> Change:
    results = spec.repositories.results
    detail = (
        f"{len(spec.datasets)} datasets, {len(spec.repositories.triggers)} triggers, results {repo_path_of(results.repository)}"
        + ("" if spec.enabled else ", stays disabled")
    )
    return Change(CREATE, "project", spec.name, detail, key=spec.name)


def update_project(spec: ProjectSpec, current: ProjectState) -> list[Change]:
    fields = [compare("enabled", current.enabled, spec.enabled)]
    warnings = []
    separate = []

    assigned = {name.lower() for name in current.datasets}
    fields += [FieldChange("datasets", None, name) for name in spec.datasets if name.lower() not in assigned]
    if current.default_dataset and spec.datasets and spec.datasets[0].lower() != current.default_dataset.lower():
        separate.append(Change(
            BLOCKED, "project", spec.name,
            f"its default dataset is {current.default_dataset} but the file lists {spec.datasets[0]} first, "
            "and the backend cannot change a project's default dataset",
            key=spec.name,
        ))

    current_triggers = {trigger.repository: trigger for trigger in current.triggers}
    for trigger in spec.repositories.triggers:
        path = repo_path_of(trigger.repository)
        have = current_triggers.get(trigger.repository)
        if have is None:
            fields.append(FieldChange("triggers", None, f"{path} (watch_dir {trigger.watch_dir}, base_branch {trigger.base_branch})"))
            continue
        label = f"triggers[{path.split('/')[-1]}]"
        fields += [
            compare(f"{label}.watch_dir", have.watch_dir, trigger.watch_dir, same_dir),
            compare(f"{label}.base_branch", have.base_branch, trigger.base_branch),
            compare(f"{label}.enabled", have.enabled, trigger.enabled),
        ]

    results = spec.repositories.results
    path = repo_path_of(results.repository)
    if current.results is None:
        assignment = FieldChange("results", None, f"{path} (target_dir {results.target_dir}, base_branch {results.base_branch})")
        if current.enabled:
            separate.append(Change(
                CONFIRM, "project", spec.name, "disable and enable needed to assign its results repository",
                fields=(assignment,), warnings=("pull requests merged meanwhile get no trigger",), key=spec.name,
            ))
        else:
            fields.append(assignment)
    elif current.results.repository != results.repository:
        separate.append(Change(
            BLOCKED, "project", spec.name,
            f"its results repository is {repo_path_of(current.results.repository)}, not {path}: the backend refuses a swap "
            "(409). By hand: disable the project, delete its results assignment, then apply again",
            key=spec.name,
        ))
    else:
        moved = found([
            compare("results.target_dir", current.results.target_dir, results.target_dir, same_dir),
            compare("results.base_branch", current.results.base_branch, results.base_branch),
        ])
        fields += list(moved) + [compare("results.enabled", current.results.enabled, results.enabled)]
        if moved:
            warnings.append(EARLIER_TASKS_FAIL)

    fields = found(fields)
    if fields:
        return [Change(UPDATE, "project", spec.name, fields=fields, warnings=tuple(warnings), key=spec.name), *separate]
    return separate or [Change(UNCHANGED, "project", spec.name, key=spec.name)]


def unresolved(spec: ProjectSpec, node: NodeFile, state: BackendState) -> list[str]:
    """
    What the project is assigned that will not be on the node: neither there already nor made by this file. An entry
    of the file whose own secret is nowhere is not made, and counts as missing.
    """
    datasets = {dataset.name.lower() for dataset in state.datasets}
    datasets |= {dataset.name.lower() for dataset in node.datasets if has_secret(node, state, dataset.secret)}
    triggers = {repo.uri for repo in state.trigger_repositories}
    triggers |= {repo.uri for repo in node.repositories.triggers if has_secret(node, state, repo.secret)}
    results = {repo.uri for repo in state.results_repositories}
    results |= {repo.uri for repo in node.repositories.results if has_secret(node, state, repo.secret)}
    problems = [f"dataset {name} {NOT_FOUND}" for name in spec.datasets if name.lower() not in datasets]
    problems += [
        f"trigger repository {repo_path_of(trigger.repository)} {NOT_FOUND}"
        for trigger in spec.repositories.triggers if trigger.repository not in triggers
    ]
    if spec.repositories.results.repository not in results:
        problems.append(f"results repository {repo_path_of(spec.repositories.results.repository)} {NOT_FOUND}")
    return problems


def project_changes(node: NodeFile, state: BackendState) -> list[Change]:
    existing = {project.name: project for project in state.projects}
    changes = []
    for spec in node.projects:
        current = existing.get(spec.name)
        missing = unresolved(spec, node, state)
        if missing:
            changes.append(Change(BLOCKED, "project", spec.name, "; ".join(missing), key=spec.name))
        else:
            changes += [create_project(spec)] if current is None else update_project(spec, current)
    return changes


def diff(node: NodeFile, state: BackendState) -> list[Change]:
    """What applying the node file would do, in the order it would do it"""
    return [
        *gitea_changes(node),
        *secret_changes(node, state),
        *provider_changes(node, state),
        *repository_changes(node, state, "trigger"),
        *repository_changes(node, state, "results"),
        *dataset_changes(node, state),
        *project_changes(node, state),
    ]


def count(changes: list[Change]) -> Counter:
    return Counter(change.action for change in changes)
