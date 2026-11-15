"""
One sync and one delete per kind: the resource's spec and the nexus-api record -> the API calls that make the record
match (ADR 0032). Every sync runs on each create, update, resume and timer tick, so it compares first and sends only
what differs: a PUT resets what its body omits, and a secret's values are sent only when its source Secret changed.

A record is found by its natural key (name, label or uri) and adopted; the resource's status.nexusId is a cache.
A dependency that is not in nexus-api yet raises kopf.TemporaryError naming it, and the resource is retried.

Spec fields are the CRDs' (camelCase); the API's are snake_case.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

import kopf

from nexus_client.api import BackendAPI
from nexus_client.git_uri import normalise_provider_uri, normalise_repo_uri, repo_path_of

GH_API_BASE_URL = "https://api.github.com"

# (namespace, name) -> (the Secret's decoded data, its resourceVersion)
SecretReader = Callable[[str, str], tuple[dict[str, str], str]]


@dataclass
class Synced:
    """What a sync did: the record's id, whether it changed anything, and extra status fields"""

    nexus_id: int | None
    changed: bool
    status: dict = field(default_factory=dict)


# Field comparison, lifted from dagster/fncli/nodefile (diff.py, schema.py)

def normalise_dir(directory: str) -> str:
    """A directory the way nexus-api compares them: `specs/` and `specs` are the same"""
    return "/".join(segment for segment in directory.split("/") if segment not in ("", "."))


def same_dir(a: str, b: str) -> bool:
    return normalise_dir(a) == normalise_dir(b)


def same_uri(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


def differing(wanted: dict, current: dict, same: Mapping[str, Callable] = None) -> dict:
    """The wanted fields whose current value is not the same"""
    same = same or {}
    return {
        name: value for name, value in wanted.items()
        if not same.get(name, lambda a, b: a == b)(current[name], value)
    }


def waiting_for(missing: list[str]):
    if missing:
        raise kopf.TemporaryError(f"waiting for {', '.join(missing)}")


# GitProvider

def find_provider(api: BackendAPI, name: str, uri: str):
    providers = api.get_git_providers()
    return (
        next((p for p in providers if normalise_provider_uri(p.uri) == uri), None)
        or next((p for p in providers if p.name == name), None)
    )


def sync_provider(api: BackendAPI, name: str, spec: Mapping) -> Synced:
    uri = normalise_provider_uri(spec["uri"])
    wanted = {
        "name": name,
        "type": spec["type"],
        "uri": uri,
        "api_uri": spec.get("apiUri") or GH_API_BASE_URL,
    }
    current = find_provider(api, name, uri)
    if current is None:
        return Synced(api.get_or_create_git_provider(uri, name, wanted["type"], wanted["api_uri"]).id, True)
    data = differing(wanted, current.model_dump(), {"uri": same_uri, "api_uri": same_uri})
    if data:
        api.patch_git_provider(current.id, data)
    return Synced(current.id, bool(data))


def delete_provider(api: BackendAPI, name: str, spec: Mapping):
    current = find_provider(api, name, normalise_provider_uri(spec["uri"]))
    if current:
        api.delete_git_provider(current.id)


# NodeSecret

def secret_sources(spec: Mapping) -> dict[str, tuple[str, str]]:
    """nexus-api key -> (source Secret, its key); fromSecret takes every key under its own name"""
    if "values" in spec:
        return {key: (ref["secretKeyRef"]["name"], ref["secretKeyRef"]["key"]) for key, ref in spec["values"].items()}
    return {}


def has_secret(api: BackendAPI, label: str) -> bool:
    return any(secret["label"] == label for secret in api.get_secrets())


def sync_secret(
    api: BackendAPI, label: str, spec: Mapping, namespace: str, read_secret: SecretReader, seen: Mapping[str, str],
) -> Synced:
    """
    Sends the values when the record is missing or a source Secret's resourceVersion is not the one in status
    (`seen`). Status keeps the resourceVersions, never a value or a hash of one.
    """
    if "fromSecret" in spec:
        data, version = read_secret(namespace, spec["fromSecret"]["name"])
        versions = {spec["fromSecret"]["name"]: version}
        values = dict(data)
    else:
        read = {}
        for name in {name for name, _ in secret_sources(spec).values()}:
            read[name] = read_secret(namespace, name)
        versions = {name: version for name, (_, version) in read.items()}
        values = {key: read[name][0][source_key] for key, (name, source_key) in secret_sources(spec).items()}

    status = {"sourceVersions": versions}
    # Only the current sources: a status merge-patch never drops the key of a source no longer named
    if all(seen.get(name) == version for name, version in versions.items()) and has_secret(api, label):
        return Synced(None, False, status)
    api.upsert_secret(label, values)
    return Synced(None, True, status)


def delete_secret(api: BackendAPI, label: str, spec: Mapping):
    api.delete_secret(label)


# Repository

def find_repository(api: BackendAPI, kind: str, uri: str):
    return api.find_trigger_repository(uri) if kind == "trigger" else api.find_results_repository(uri)


def provider_for(api: BackendAPI, uri: str):
    """The provider whose host the (normalised) repository uri is on"""
    host = uri.split("/")[0]
    return next(
        (p for p in api.get_git_providers() if urlparse(normalise_provider_uri(p.uri)).netloc == host), None
    )


def sync_repository(api: BackendAPI, name: str, spec: Mapping) -> Synced:
    kind = spec["type"]
    uri = normalise_repo_uri(spec["uri"])
    provider = provider_for(api, uri)
    waiting_for(
        ([] if provider else [f"a git provider on {uri.split('/')[0]}"])
        + ([] if has_secret(api, spec["secret"]) else [f"secret {spec['secret']}"])
    )
    current = find_repository(api, kind, uri)
    if current is None:
        create = api.create_repository if kind == "trigger" else api.create_results_repository
        return Synced(create(provider.id, repo_path_of(uri), spec["secret"]).id, True)
    data = differing(
        {"provider_id": provider.id, "secret_label": spec["secret"]},
        {"provider_id": current.provider.id, "secret_label": current.secret.label},
    )
    if data:
        patch = api.patch_trigger_repository if kind == "trigger" else api.patch_results_repository
        patch(current.id, data)
    return Synced(current.id, bool(data))


def delete_repository(api: BackendAPI, name: str, spec: Mapping):
    current = find_repository(api, spec["type"], normalise_repo_uri(spec["uri"]))
    if current:
        delete = api.delete_repository if spec["type"] == "trigger" else api.delete_results_repository
        delete(current.id)


# Dataset

def sync_dataset(api: BackendAPI, name: str, spec: Mapping) -> Synced:
    waiting_for([] if has_secret(api, spec["secret"]) else [f"secret {spec['secret']}"])
    wanted = {
        "host": spec["host"],
        "port": spec["port"],
        "type": spec["type"],
        "read_schema": spec.get("readSchema"),
        "write_schema": spec.get("writeSchema"),
        "secret_label": spec["secret"],
    }
    current = api.find_dataset(name)
    if current is None:
        dataset = api.create_dataset(
            name, wanted["host"], wanted["port"], wanted["type"], wanted["secret_label"],
            read_schema=wanted["read_schema"], write_schema=wanted["write_schema"],
        )
        return Synced(dataset.id, True)
    data = differing(wanted, {**current.model_dump(), "secret_label": current.secret.label})
    if data:
        api.patch_dataset(current.id, data)
    return Synced(current.id, bool(data))


def delete_dataset(api: BackendAPI, name: str, spec: Mapping):
    current = api.find_dataset(name)
    if current:
        api.delete_dataset(current.id)


# Project

def resolve_project(api: BackendAPI, spec: Mapping) -> tuple[dict, dict, object]:
    """The datasets, trigger repositories and results repository the project names, or wait for those missing"""
    datasets = {name: api.find_dataset(name) for name in spec.get("datasets", [])}
    triggers = {
        trigger["repository"]: api.find_trigger_repository(trigger["repository"])
        for trigger in spec["repositories"].get("triggers", [])
    }
    results_uri = spec["repositories"]["results"]["repository"]
    results = api.find_results_repository(results_uri)
    waiting_for(
        [f"dataset {name}" for name, dataset in datasets.items() if dataset is None]
        + [f"trigger repository {uri}" for uri, repo in triggers.items() if repo is None]
        + ([] if results else [f"results repository {results_uri}"])
    )
    return datasets, triggers, results


def sync_project(api: BackendAPI, name: str, spec: Mapping) -> Synced:
    """
    Created disabled and enabled last. Datasets are assigned in the order given (the first becomes the default);
    an assignment that exists is PATCHed with the fields that differ. A results repository is assigned only to a
    disabled project, so a live project is disabled for it and enabled again by the last step.
    """
    datasets, triggers, results = resolve_project(api, spec)
    project = api.find_project(name)
    changed = project is None
    if project is None:
        project = api.get_or_create_project(name)
    enabled = project.enabled

    assigned = {a.dataset.id for a in api.get_project_datasets(project.id)}
    for dataset in datasets.values():
        if dataset.id not in assigned:
            api.get_or_assign_dataset(project.id, dataset)
            changed = True

    assigned = {a.trigger_repository.id: a for a in api.get_project_trigger_repositories(project.id)}
    for trigger in spec["repositories"].get("triggers", []):
        repo = triggers[trigger["repository"]]
        wanted = {
            "watch_dir": trigger["watchDir"], "base_branch": trigger["baseBranch"],
            "enabled": trigger.get("enabled", True),
        }
        current = assigned.get(repo.id)
        if current is None:
            api.put_project_trigger_repository(project.id, repo.id, **wanted)
            changed = True
            continue
        data = differing(wanted, current.model_dump(), {"watch_dir": same_dir})
        if data:
            api.patch_project_trigger_repository(project.id, repo.id, data)
            changed = True

    spec_results = spec["repositories"]["results"]
    wanted = {
        "target_dir": spec_results["targetDir"], "base_branch": spec_results["baseBranch"],
        "enabled": spec_results.get("enabled", True),
    }
    current = next(iter(api.get_project_results_repositories(project.id)), None)
    if current is None or current.results_repository.id != results.id:
        if enabled:
            api.patch_project(project.id, {"enabled": False})
            enabled = False
        api.put_project_results_repository(project.id, results.id, **wanted)
        changed = True
    else:
        data = differing(wanted, current.model_dump(), {"target_dir": same_dir})
        if data:
            api.patch_project_results_repository(project.id, results.id, data)
            changed = True

    if enabled != spec.get("enabled", True):
        api.patch_project(project.id, {"enabled": spec.get("enabled", True)})
        changed = True
    return Synced(project.id, changed)


def delete_project(api: BackendAPI, name: str, spec: Mapping):
    current = api.find_project(name)
    if current:
        api.delete_project(current.id)
