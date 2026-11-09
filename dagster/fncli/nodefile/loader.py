"""
Load a node file (schema.py): parse the YAML, validate it, resolve its paths, and run the checks that need no API
call. Every problem found is reported at once, in one ClickException. The checks across projects on the same repository
(trigger and results directories) are only made within the file: the backend sees every project on the node, so it
stays the final judge. So are the references to what the file does not hold (a project's dataset, a repository's
secret, ...): they may be on the node, which only the diff reads (diff.py).
"""

import os
from dataclasses import dataclass
from pathlib import Path

import click
import yaml
from kubernetes.client.exceptions import ApiException
from pydantic import ValidationError

from fncli.k8s import get_k8s_secret
from fncli.nodefile.schema import (
    EnvRef, FileRef, GenerateRef, K8sSecretRef, NodeFile, SecretSpec, dirs_overlap,
)

SET, MISSING, GENERATED = "set", "missing", "generated"


class UniqueKeyLoader(yaml.SafeLoader):
    """A mapping with the same key twice is an error, not the last one winning"""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        duplicates = sorted({str(key) for key in keys if keys.count(key) > 1})
        if duplicates:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate keys: {', '.join(duplicates)}", node.start_mark
            )
        return super().construct_mapping(node, deep=deep)


def where(loc: tuple) -> str:
    """A pydantic error location as a path in the file: projects[0].repositories.results.target_dir"""
    parts = [part for i, part in enumerate(loc) if not (i + 1 < len(loc) and loc[i + 1] == part) and part != "invalid"]
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else f".{part}" if text else str(part)
    return text or "the file"


def fail(path: Path, problems: list[str]):
    listing = "\n".join(f"  - {problem}" for problem in problems)
    raise click.ClickException(f"{path} has {len(problems)} problem{'s' * (len(problems) != 1)}:\n{listing}")


def load_node_file(path: Path) -> NodeFile:
    """The node file at path, checked. Raises one ClickException that lists every problem."""
    try:
        data = yaml.load(path.read_text(), Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise click.ClickException(f"{path} is not valid YAML: {error}") from error
    try:
        node = NodeFile.model_validate(data)
    except ValidationError as error:
        # loc and msg only: an error's input could be a value that was not meant to be in the file
        fail(path, [f"{where(e['loc'])}: {e['msg'].removeprefix('Value error, ')}" for e in error.errors()])
    resolve_paths(node, path.resolve().parent)
    problems = check(node, node.node.gitea_admin_user)
    if problems:
        fail(path, problems)
    return node


def resolve_paths(node: NodeFile, base_dir: Path):
    """
    `~` expanded, and a path relative to the node file made absolute. The env file is looked for from the node
    file's directory up, so `.dev.env` finds the repo root's; one not found is left as written, for diff to report.
    """
    for spec in node.secrets.values():
        for reference in (spec.values or {}).values():
            if isinstance(reference, FileRef):
                reference.file = base_dir / reference.file.expanduser()
    env_file = node.node.env_file
    if env_file is not None:
        env_file = env_file.expanduser()
        found = next((d / env_file for d in (base_dir, *base_dir.parents) if (d / env_file).is_file()), None)
        node.node.env_file = found or env_file


def duplicates(names: list[str]) -> list[str]:
    return sorted({name for name in names if names.count(name) > 1})


def check(node: NodeFile, gitea_admin_user: str) -> list[str]:
    """What is wrong with the file beyond its shape: names used twice, hosts without a provider, and loops"""
    problems = []
    trigger_uris = [repo.uri for repo in node.repositories.triggers]
    results_uris = [repo.uri for repo in node.repositories.results]
    dataset_names = [dataset.name.lower() for dataset in node.datasets]

    for label, names in (
        ("provider uri", [provider.uri for provider in node.providers]),
        ("trigger repository", trigger_uris),
        ("results repository", results_uris),
        ("dataset name", dataset_names),
        ("project name", [project.name for project in node.projects]),
    ):
        problems += [f"{label} {name} is listed twice" for name in duplicates(names)]

    for kind, repos in (("triggers", node.repositories.triggers), ("results", node.repositories.results)):
        for i, repo in enumerate(repos):
            provider = node.provider_for(repo.uri)
            if provider is None:
                problems.append(f"repositories.{kind}[{i}]: no provider for the host of {repo.uri}")
            elif provider.type == "gitea":
                owner = repo.uri.split("/")[-2]
                if owner != gitea_admin_user.lower():
                    problems.append(
                        f"repositories.{kind}[{i}]: {repo.uri} is owned by {owner}, not the Gitea admin user "
                        f"{gitea_admin_user}"
                    )

    apps = [spec.gitea_oauth.app for spec in node.secrets.values() if spec.gitea_oauth]
    problems += [f"Gitea OAuth app name {app} is used twice, and Gitea tells apps apart by name" for app in duplicates(apps)]
    if apps and node.gitea is None:
        problems.append("a gitea_oauth secret needs the gitea section")
    if node.gitea is not None:
        gitea_provider = next((p for p in node.providers if p.resolved_name == node.gitea.provider), None)
        if gitea_provider is None or gitea_provider.type != "gitea":
            problems.append(f"gitea.provider {node.gitea.provider} is not the name of a gitea provider above")

    results_by_repo = {}
    for i, project in enumerate(node.projects):
        at = f"projects[{i}] ({project.name})"
        problems += [f"{at}: dataset {name} is listed twice" for name in duplicates([d.lower() for d in project.datasets])]
        triggers = project.repositories.triggers
        problems += [f"{at}: trigger {uri} is listed twice" for uri in duplicates([t.repository for t in triggers])]
        results = project.repositories.results
        results_by_repo.setdefault(results.repository, []).append((project.name, results.target_dir))

    for project in node.projects:
        for trigger in project.repositories.triggers:
            for results_project, target_dir in results_by_repo.get(trigger.repository, []):
                if dirs_overlap(trigger.watch_dir, target_dir):
                    problems.append(
                        f"project {project.name}: watch_dir {trigger.watch_dir} and project {results_project}'s results "
                        f"target_dir {target_dir} overlap in {trigger.repository}, so results would trigger themselves"
                    )
    return problems


def limit_to_project(node: NodeFile, name: str) -> NodeFile:
    """The node file reduced to one project and the global resources it references"""
    project = next((project for project in node.projects if project.name == name), None)
    if project is None:
        raise click.ClickException(
            f"Project {name} is not in the node file, which has: {', '.join(p.name for p in node.projects)}"
        )
    trigger_uris = {trigger.repository for trigger in project.repositories.triggers}
    results_uri = project.repositories.results.repository
    dataset_names = {dataset.lower() for dataset in project.datasets}
    triggers = [repo for repo in node.repositories.triggers if repo.uri in trigger_uris]
    results = [repo for repo in node.repositories.results if repo.uri == results_uri]
    datasets = [dataset for dataset in node.datasets if dataset.name.lower() in dataset_names]
    labels = {repo.secret for repo in triggers + results} | {dataset.secret for dataset in datasets}
    provider_uris = {node.provider_for(repo.uri).uri for repo in triggers + results}
    return node.model_copy(update={
        "providers": [provider for provider in node.providers if provider.uri in provider_uris],
        "secrets": {label: spec for label, spec in node.secrets.items() if label in labels},
        "repositories": node.repositories.model_copy(update={"triggers": triggers, "results": results}),
        "datasets": datasets,
        "projects": [project],
    })


@dataclass(frozen=True)
class Source:
    """Where one value of a secret is read from, and whether it can be: never the value itself"""

    key: str
    where: str
    state: str


def k8s_secret_state(reference: K8sSecretRef) -> str:
    source = reference.k8s_secret
    try:
        get_k8s_secret(source.name, source.namespace, source.key)
    except ApiException as error:
        if error.status != 404:
            raise
        return MISSING
    except KeyError:
        return MISSING
    return SET


def check_sources(spec: SecretSpec) -> list[Source]:
    """Whether each value of a secret can be read at apply time. A gitea_oauth secret has no values to read."""
    sources = []
    for key, reference in (spec.values or {}).items():
        match reference:
            case EnvRef():
                sources.append(Source(key, f"env {reference.env}", SET if os.environ.get(reference.env) else MISSING))
            case FileRef():
                sources.append(Source(key, f"file {reference.file}", SET if reference.file.is_file() else MISSING))
            case K8sSecretRef():
                source = reference.k8s_secret
                location = f"k8s secret {source.namespace}/{source.name} key {source.key}"
                sources.append(Source(key, location, k8s_secret_state(reference)))
            case GenerateRef():
                sources.append(Source(key, f"random, {reference.generate.length} characters", GENERATED))
    return sources
