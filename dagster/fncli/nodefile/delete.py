"""
What `fncli delete` deletes, and how: the projects the node file describes, and with --all its repositories, datasets,
secrets and providers, as far as the node has them, through nexus-api's DELETE routes, which soft-delete. The projects
go with their assignments. Never with ?force=true: a global resource that a project outside the file still uses is
refused by the backend (409), and is skipped, not forced. A provider other repositories are on is kept without asking.
What fncli made in Gitea (repositories, OAuth apps) is left alone.
"""

import requests

from fncli.backend import FncliBackendAPI, repo_path_of
from fncli.nodefile import lookup
from fncli.nodefile.diff import UNCHANGED, BackendState, Change, ProjectState, users
from fncli.nodefile.schema import NodeFile

DELETE = "delete"
# Reverse of apply: what uses a thing goes before it
ORDER = ("project", "trigger repo", "results repo", "dataset", "secret", "provider")
DETAILS = {"project": "with its assignments", "secret": "and its stored values"}


def refusal(error: requests.HTTPError) -> str:
    """The backend's reason for refusing a request, and the projects it names"""
    body = error.response.json()
    projects = ", ".join(item["name"] for item in body.get("details", []))
    return body["error"] + (f" (projects: {projects})" if projects else "")


def uses_trigger(project: ProjectState, uri: str) -> bool:
    return any(trigger.repository == uri for trigger in project.triggers)


def uses_results(project: ProjectState, uri: str) -> bool:
    return project.results is not None and project.results.repository == uri


def deletions(node: NodeFile, state: BackendState, with_globals: bool) -> tuple[list[Change], int]:
    """
    The rows that delete what the file describes and the node has (its projects, and with_globals its global
    resources), in order, and how many of what the file describes are not on the node. A global resource lists the
    projects outside the file that use it: the backend refuses to delete it for them. A provider that repositories
    outside the file are on is a row that keeps it (UNCHANGED), not a refusal to wait for.
    """
    changes = []
    on_node = {project.name for project in state.projects}
    changes += [
        Change(DELETE, "project", project.name, DETAILS["project"], key=project.name)
        for project in node.projects if project.name in on_node
    ]
    described = len(node.projects)
    if with_globals:
        for entity, specs, existing, uses in (
            ("trigger", node.repositories.triggers, state.trigger_repositories, uses_trigger),
            ("results", node.repositories.results, state.results_repositories, uses_results),
        ):
            on_node = {repo.uri for repo in existing}
            for spec in specs:
                if spec.uri in on_node:
                    used = users(node, state, lambda project: uses(project, spec.uri))
                    changes.append(Change(DELETE, f"{entity} repo", repo_path_of(spec.uri), also_used_by=used, key=spec.uri))
            described += len(specs)
        on_node = {dataset.name.lower() for dataset in state.datasets}
        for spec in node.datasets:
            if spec.name.lower() in on_node:
                used = users(node, state, lambda project: spec.name.lower() in {name.lower() for name in project.datasets})
                changes.append(Change(DELETE, "dataset", spec.name, also_used_by=used, key=spec.name))
        changes += [
            Change(DELETE, "secret", label, DETAILS["secret"], key=label) for label in node.secrets if label in state.secrets
        ]
        on_node = {provider.uri for provider in state.providers}
        listed_repos = {repo.uri for repo in node.repositories.triggers + node.repositories.results}
        for spec in node.providers:
            if spec.uri not in on_node:
                continue
            others = [
                repo for repo in state.trigger_repositories + state.results_repositories
                if repo.provider == spec.uri and repo.uri not in listed_repos
            ]
            if others:
                changes.append(Change(
                    UNCHANGED, "provider", spec.resolved_name, f"kept, {len(others)} repositories outside the file are on it",
                    key=spec.uri,
                ))
            else:
                changes.append(Change(DELETE, "provider", spec.resolved_name, key=spec.uri))
        described += len(node.datasets) + len(node.secrets) + len(node.providers)
    return sorted(changes, key=lambda change: ORDER.index(change.kind)), described - len(changes)


class Remover:
    """Deletes one thing at a time from the backend, without force"""

    def __init__(self, api: FncliBackendAPI):
        self.api = api

    def run(self, change: Change):
        api = self.api
        match change.kind:
            case "project":
                api.delete_project(lookup.project_id(api, change.key))
            case "trigger repo":
                api.delete_repository(lookup.repository_id(api, "trigger", change.key), force=False)
            case "results repo":
                api.delete_results_repository(lookup.repository_id(api, "results", change.key), force=False)
            case "dataset":
                api.delete_dataset(lookup.dataset_id(api, change.key), force=False)
            case "secret":
                api.delete_secret(change.key)
            case "provider":
                api.delete_git_provider(lookup.provider_id(api, change.key))
