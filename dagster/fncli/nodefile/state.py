"""
The backend's state as the diff reads it (diff.BackendState), from FncliBackendAPI's read calls. All of it is read
whatever the plan is limited to, because the plan lists the other projects assigned to a global resource that changes.
"""

from app.git_uri import normalise_provider_uri, normalise_repo_uri
from app.models import Project
from fncli.backend import FncliBackendAPI
from fncli.nodefile.diff import (
    BackendState, DatasetState, ProjectState, ProviderState, RepositoryState, ResultsState, TriggerState,
)


def read_project(api: FncliBackendAPI, project: Project) -> ProjectState:
    datasets = api.get_project_datasets(project.id)
    default = next((a.dataset.name for a in datasets if a.dataset.id == project.default_dataset_id), None)
    results = api.get_project_results_repositories(project.id)
    return ProjectState(
        name=project.name,
        enabled=project.enabled,
        datasets=[assignment.dataset.name for assignment in datasets],
        default_dataset=default,
        triggers=[
            TriggerState(
                normalise_repo_uri(a.trigger_repository.uri), a.watch_dir, a.base_branch, a.enabled
            )
            for a in api.get_project_trigger_repositories(project.id)
        ],
        results=ResultsState(
            normalise_repo_uri(results[0].results_repository.uri),
            results[0].target_dir, results[0].base_branch, results[0].enabled,
        ) if results else None,
    )


def read_state(api: FncliBackendAPI) -> BackendState:
    """Read the providers, secrets, repositories, datasets and projects (with their assignments) of the node"""
    return BackendState(
        providers=[
            ProviderState(p.name, p.type, normalise_provider_uri(p.uri), p.api_uri) for p in api.get_git_providers()
        ],
        secrets={secret["label"] for secret in api.get_secrets()},
        trigger_repositories=[
            RepositoryState(normalise_repo_uri(r.uri), normalise_provider_uri(r.provider.uri), r.secret.label)
            for r in api.get_trigger_repositories()
        ],
        results_repositories=[
            RepositoryState(normalise_repo_uri(r.uri), normalise_provider_uri(r.provider.uri), r.secret.label)
            for r in api.get_results_repositories()
        ],
        datasets=[
            DatasetState(d.name, d.type, d.host, d.port, d.read_schema, d.write_schema, d.secret.label)
            for d in api.get_datasets()
        ],
        projects=[read_project(api, project) for project in api.get_projects()],
    )
