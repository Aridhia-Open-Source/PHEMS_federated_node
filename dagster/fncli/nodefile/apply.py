"""
Carry out what the diff found (`fncli apply`), one change at a time, in dependency order. This is the only part of
the node-file code that writes.

What is sent comes from the file's entries, typed, never from a Change: a Change says which fields differ, not what to
send (its values are text for the plan). A repeated apply must not undo what someone set by hand, so a secret is only
written when missing or with --rotate (which is also the only time a gitea_oauth secret authorises its OAuth app again,
as that replaces the app's client secret), and an assignment that exists is only ever PATCHed with the fields that
differ: a PUT resets what its body omits.
"""

import os
import secrets
import string

import click
import requests

from app.models import Project
from fncli.backend import FncliBackendAPI, repo_path_of
from fncli.gitea import GiteaAdminAPI
from fncli.k8s import get_k8s_secret
from fncli.nodefile import lookup
from fncli.nodefile.diff import (
    BackendState, CONFIRM, CREATE, ENSURE, UNCHANGED, UPDATE, Change, describe_secret,
)
from fncli.nodefile.loader import MISSING, check_sources
from fncli.nodefile.schema import (
    EnvRef, FileRef, GenerateRef, K8sSecretRef, NodeFile, ProjectSpec, ResultsAssignment, TriggerAssignment,
)

# Dependency order: a repository needs its provider and secret, a dataset its secret, a project all of them
ORDER = ("secret", "provider", "gitea repo", "trigger repo", "results repo", "dataset", "project")
RANDOM_CHARACTERS = string.ascii_letters + string.digits


def describe_error(error: Exception) -> str:
    """What went wrong, with the backend's reason for a refused request"""
    if isinstance(error, requests.HTTPError):
        return f"{error} - {error.response.text[:300]}"
    return f"{type(error).__name__}: {error}"


def with_rotations(node: NodeFile, changes: list[Change], labels: tuple[str, ...]) -> list[Change]:
    """The secrets that exist and are to be rewritten (--rotate) as changes, so the plan shows them"""
    unknown = [label for label in labels if label not in node.secrets]
    if unknown:
        raise click.ClickException(
            f"--rotate: {', '.join(unknown)} is not a secret of the node file (with --project, of that project)"
        )
    return [
        Change(
            UPDATE, "secret", change.name, f"rewritten (--rotate), {describe_secret(node.secrets[change.key])}",
            key=change.key,
        )
        if change.kind == "secret" and change.action == UNCHANGED and change.key in labels else change
        for change in changes
    ]


def to_do(changes: list[Change]) -> list[Change]:
    """The changes apply carries out, in the order it does. Blocked and unchanged ones are left alone."""
    return sorted(
        (change for change in changes if change.action in (CREATE, UPDATE, CONFIRM, ENSURE)),
        key=lambda change: ORDER.index(change.kind),
    )


def writes_secret(change: Change) -> bool:
    return change.kind == "secret" and change.action in (CREATE, UPDATE)


def missing_sources(node: NodeFile, changes: list[Change]) -> list[str]:
    """What the secrets about to be written read their values from, and cannot"""
    return [
        f"secret {change.key}, {source.key}: {source.where}"
        for change in changes if writes_secret(change)
        for source in check_sources(node.secrets[change.key]) if source.state == MISSING
    ]


def needs_gitea(node: NodeFile, changes: list[Change]) -> bool:
    """Whether a change calls Gitea: a repository to ensure, or an OAuth app to authorise"""
    return any(
        change.kind == "gitea repo" or (writes_secret(change) and node.secrets[change.key].gitea_oauth)
        for change in changes
    )


def read_value(reference) -> str:
    """The value a secret's reference points at, read now"""
    match reference:
        case EnvRef():
            return os.environ[reference.env]
        case FileRef():
            # What `$(cat key.pem)` gave the env-based setup: no trailing newline
            return reference.file.read_text().rstrip("\n")
        case K8sSecretRef():
            source = reference.k8s_secret
            return get_k8s_secret(source.name, source.namespace, source.key)
        case GenerateRef():
            return "".join(secrets.choice(RANDOM_CHARACTERS) for _ in range(reference.generate.length))


class Applier:
    """Carries out one change at a time on the backend, and on Gitea when the node file has a `gitea` section"""

    def __init__(self, node: NodeFile, state: BackendState, api: FncliBackendAPI, gitea: GiteaAdminAPI | None):
        self.node = node
        self.api = api
        self.gitea = gitea
        self.current = {project.name: project for project in state.projects}
        self.providers = {provider.uri: provider for provider in node.providers}
        self.repositories = {
            "trigger": {repo.uri: repo for repo in node.repositories.triggers},
            "results": {repo.uri: repo for repo in node.repositories.results},
        }
        self.datasets = {dataset.name: dataset for dataset in node.datasets}
        self.projects = {project.name: project for project in node.projects}

    def run(self, change: Change):
        handler = {
            ("gitea repo", ENSURE): self.ensure_gitea_repo,
            ("secret", CREATE): self.write_secret,
            ("secret", UPDATE): self.write_secret,
            ("provider", CREATE): self.create_provider,
            ("provider", UPDATE): self.update_provider,
            ("trigger repo", CREATE): self.create_repository,
            ("trigger repo", UPDATE): self.update_repository,
            ("results repo", CREATE): self.create_repository,
            ("results repo", UPDATE): self.update_repository,
            ("dataset", CREATE): self.create_dataset,
            ("dataset", UPDATE): self.update_dataset,
            ("project", CREATE): self.create_project,
            ("project", UPDATE): self.update_project,
            ("project", CONFIRM): self.assign_results_to_live_project,
        }[(change.kind, change.action)]
        handler(change)

    def ensure_gitea_repo(self, change: Change):
        self.gitea.get_or_create_repo(repo_path_of(change.key).split("/")[1])

    def write_secret(self, change: Change):
        spec = self.node.secrets[change.key]
        if spec.gitea_oauth:
            tokens = self.gitea.authorize_oauth_app(spec.gitea_oauth.app)
            values = {
                "CLIENT_ID": tokens["client_id"],
                "CLIENT_SECRET": tokens["client_secret"],
                "REFRESH_TOKEN": tokens["refresh_token"],
            }
        else:
            values = {key: read_value(reference) for key, reference in spec.values.items()}
        self.api.upsert_secret(change.key, values)

    def create_provider(self, change: Change):
        spec = self.providers[change.key]
        self.api.get_or_create_git_provider(spec.uri, spec.resolved_name, spec.type, spec.api_uri)

    def update_provider(self, change: Change):
        spec = self.providers[change.key]
        self.api.patch_git_provider(
            lookup.provider_id(self.api, spec.uri), {field.field: getattr(spec, field.field) for field in change.fields}
        )

    def create_repository(self, change: Change):
        entity = change.kind.split()[0]
        spec = self.repositories[entity][change.key]
        provider_id = lookup.provider_id(self.api, self.node.provider_for(spec.uri).uri)
        create = self.api.create_repository if entity == "trigger" else self.api.create_results_repository
        create(provider_id, repo_path_of(spec.uri), spec.secret)

    def update_repository(self, change: Change):
        entity = change.kind.split()[0]
        spec = self.repositories[entity][change.key]
        fields = {field.field for field in change.fields}
        data = {}
        if "secret" in fields:
            data["secret_label"] = spec.secret
        if "provider" in fields:
            data["provider_id"] = lookup.provider_id(self.api, self.node.provider_for(spec.uri).uri)
        patch = self.api.patch_trigger_repository if entity == "trigger" else self.api.patch_results_repository
        patch(lookup.repository_id(self.api, entity, spec.uri), data)

    def create_dataset(self, change: Change):
        spec = self.datasets[change.key]
        self.api.create_dataset(
            spec.name, spec.host, spec.port, spec.type, spec.secret,
            read_schema=spec.read_schema, write_schema=spec.write_schema,
        )

    def update_dataset(self, change: Change):
        spec = self.datasets[change.key]
        data = {("secret_label" if field.field == "secret" else field.field): getattr(spec, field.field) for field in change.fields}
        self.api.patch_dataset(lookup.dataset_id(self.api, spec.name), data)

    def assign_datasets(self, project_id: int, names: list[str]):
        """In the order given: the first dataset a project is assigned becomes its default"""
        for name in names:
            self.api.get_or_assign_dataset(project_id, lookup.present(self.api.find_dataset(name), f"dataset {name}"))

    def put_trigger(self, project_id: int, trigger: TriggerAssignment):
        self.api.put_project_trigger_repository(
            project_id, lookup.repository_id(self.api, "trigger", trigger.repository),
            trigger.watch_dir, trigger.base_branch, trigger.enabled,
        )

    def put_results(self, project_id: int, results: ResultsAssignment):
        self.api.put_project_results_repository(
            project_id, lookup.repository_id(self.api, "results", results.repository),
            results.target_dir, results.base_branch, results.enabled,
        )

    def ensure_project(self, spec: ProjectSpec) -> Project:
        """The project, created disabled, which a results repository needs, if it is not there"""
        return self.api.get_or_create_project(spec.name)

    def create_project(self, change: Change):
        """Created disabled, and enabled last when the file says so"""
        spec = self.projects[change.key]
        project = self.ensure_project(spec)
        self.assign_datasets(project.id, spec.datasets)
        for trigger in spec.repositories.triggers:
            self.put_trigger(project.id, trigger)
        self.put_results(project.id, spec.repositories.results)
        if spec.enabled:
            self.api.patch_project(project.id, {"enabled": True})

    def update_project(self, change: Change):
        """New assignments are PUT, existing ones PATCHed with the fields that differ, and the project's own flag is last"""
        spec = self.projects[change.key]
        fields = {field.field for field in change.fields}
        project_id = lookup.project_id(self.api, spec.name)

        added = {field.new for field in change.fields if field.field == "datasets"}
        self.assign_datasets(project_id, [name for name in spec.datasets if name in added])

        assigned = {trigger.repository for trigger in self.current[spec.name].triggers}
        for trigger in spec.repositories.triggers:
            if trigger.repository not in assigned:
                self.put_trigger(project_id, trigger)
                continue
            label = f"triggers[{repo_path_of(trigger.repository).split('/')[-1]}]"
            data = {name: getattr(trigger, name) for name in ("watch_dir", "base_branch", "enabled") if f"{label}.{name}" in fields}
            if data:
                self.api.patch_project_trigger_repository(project_id, lookup.repository_id(self.api, "trigger", trigger.repository), data)

        results = spec.repositories.results
        if "results" in fields:
            self.put_results(project_id, results)
        else:
            data = {name: getattr(results, name) for name in ("target_dir", "base_branch", "enabled") if f"results.{name}" in fields}
            if data:
                self.api.patch_project_results_repository(project_id, lookup.repository_id(self.api, "results", results.repository), data)

        if "enabled" in fields:
            self.api.patch_project(project_id, {"enabled": spec.enabled})

    def assign_results_to_live_project(self, change: Change):
        """The backend assigns a results repository only to a disabled project: disable, assign, enable again"""
        spec: ProjectSpec = self.projects[change.key]
        project_id = lookup.project_id(self.api, spec.name)
        self.api.patch_project(project_id, {"enabled": False})
        try:
            self.put_results(project_id, spec.repositories.results)
            if spec.enabled:
                self.api.patch_project(project_id, {"enabled": True})
        except Exception as error:
            raise RuntimeError(
                f"{describe_error(error)}; project {spec.name} is left disabled, apply again to finish"
            ) from error
