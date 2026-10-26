"""
Healthcheck endpoints. A failed check is reported in the body, still with a 200. Nothing
returned includes a secret's value. Each resource has one check, run for the global
resource and for a project's resource for it (which adds the project resource's state, and a 404 if the
project has none); the roll-ups are built from the same per-resource functions. Whatever
reads the database or the cluster happens in the request (the prepare_* functions), and
only the network calls run in the threads.
- GET /global/healthcheck, every global resource of the four kinds
- GET /global/datasets/<dataset_id>/healthcheck, can the node connect to its database
- GET /global/secrets/<label>/healthcheck, is it in its store with the keys its users need
- GET /global/providers/<provider_id>/healthcheck, does the git provider's API answer
- GET /global/repositories/triggers/<repository_id>/healthcheck
- GET /global/repositories/results/<repository_id>/healthcheck
- GET /projects/<project_id>/healthcheck, the project's trigger and results repository resources
- GET /projects/<project_id>/datasets/<dataset_id>/healthcheck
- GET /projects/<project_id>/secrets/<label>/healthcheck
- GET /projects/<project_id>/repositories/triggers/<repository_id>/healthcheck
- GET /projects/<project_id>/repositories/results/<repository_id>/healthcheck
"""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends

from app.dtos.healthcheck import (
    DatasetHealthDTO, GitProviderHealthDTO, GlobalHealthDTO, ProjectDatasetHealthDTO, ProjectResultsRepositoryHealthDTO,
    ProjectSecretHealthDTO, ProjectTriggerRepositoryHealthDTO, RepositoryConnectionDTO, SecretHealthDTO
)
from app.dtos.project import HealthCheckDTO, ProjectHealthDTO, RepositoryHealthDTO, ResultsRepositoryHealthDTO
from app.helpers.exceptions import DBRecordNotFoundError
from app.helpers.wrappers import require_scope
from app.models.dataset import Dataset
from app.models.git_provider import ConnectionCheck, ConnectionStatus, GitProvider
from app.models.git_repository import GitRepositoryMixin
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret
from app.models.trigger_repository import TriggerRepository
from app.projects_api import _dataset_resource, _results_resource, _secret_resource
from app.secrets_api import SecretProvider, _get_secret

HEALTHCHECK_MAX_WORKERS = 8

router = APIRouter(tags=["healthcheck"], dependencies=[Depends(require_scope('can_admin_dataset'))])


def _trigger_resource(project_id: int, repository_id: int) -> ProjectTriggerRepository:
    """The project's resource for a global trigger repository, found by the repository's id."""
    resource = ProjectTriggerRepository.query.filter_by(
        trigger_repository_id=repository_id, project_id=project_id
    ).one_or_none()
    if resource is None:
        raise DBRecordNotFoundError(f"Trigger repository {repository_id} is not assigned to project {project_id}")
    return resource


def _health_check(check: ConnectionCheck) -> HealthCheckDTO:
    return HealthCheckDTO(message=check.message, status_code=check.status_code, latency_ms=check.latency_ms)


def _run_all(checks: list[Callable]) -> list:
    with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as executor:
        return list(executor.map(lambda check: check(), checks))


def _is_ok(items) -> bool:
    return all(item.status == ConnectionStatus.OK for item in items)


def prepare_repository_health(repository: GitRepositoryMixin) -> Callable[[], RepositoryConnectionDTO]:
    """A global trigger or results repository: can it be reached with its own secret."""
    id, uri, provider, enabled = repository.id, repository.uri, repository.provider.type, repository.enabled
    prepared = repository.prepare_connection_check()

    def run():
        check = prepared()
        return RepositoryConnectionDTO(
            id=id, uri=uri, provider=provider, enabled=enabled,
            status=check.status.value, health_check=_health_check(check),
        )
    return run


def prepare_provider_health(provider: GitProvider) -> Callable[[], GitProviderHealthDTO]:
    """A global git provider: does its API answer, without a token."""
    id, name, type, uri, api_uri, enabled = (
        provider.id, provider.name, provider.type, provider.uri, provider.api_uri, provider.enabled
    )
    prepared = provider.prepare_connection_check()

    def run():
        check = prepared()
        return GitProviderHealthDTO(
            id=id, name=name, type=type, uri=uri, api_uri=api_uri, enabled=enabled,
            status=check.status.value, health_check=_health_check(check),
        )
    return run


def prepare_dataset_health(dataset: Dataset) -> Callable[[], DatasetHealthDTO]:
    """A global dataset: can the node connect to its database with its secret."""
    prepared = dataset.prepare_connection_check()
    id, name, host, port, type, enabled = dataset.id, dataset.name, dataset.host, dataset.port, dataset.type, dataset.enabled

    def run():
        check = prepared()
        return DatasetHealthDTO(
            id=id, name=name, host=host, port=port, type=type, enabled=enabled,
            status=check.status.value, health_check=_health_check(check),
        )
    return run


def prepare_secret_health(secret: Secret) -> Callable[[], SecretHealthDTO]:
    """
    A global secret: is it in its store, with the keys its datasets and repositories read.
    A secret nothing uses needs no particular key. A disabled one is reported as not readable
    (secret_missing, saying it is disabled) without looking in the store, its value being in quarantine.
    """
    expected = set()
    if secret.datasets:
        expected |= set(Dataset.SECRET_KEYS)
    if secret.trigger_repositories or secret.results_repositories:
        expected |= set(GitRepositoryMixin.SECRET_KEYS)
    if not secret.enabled:
        # Its value is in quarantine, out of reach on purpose: not read
        keys = []
        check = ConnectionCheck(ConnectionStatus.SECRET_MISSING, f"Secret {secret.label} is disabled, so it cannot be read")
    else:
        keys = SecretProvider(secret.provider).keys(secret.key, secret.namespace)
        if keys is None:
            check = ConnectionCheck(ConnectionStatus.SECRET_MISSING, f"Secret {secret.label} is not in its store")
            keys = []
        elif expected - set(keys):
            check = ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {secret.label} has no {', '.join(sorted(expected - set(keys)))}"
            )
        else:
            check = ConnectionCheck(ConnectionStatus.OK, "OK")
    health = SecretHealthDTO(
        label=secret.label, provider=secret.provider, enabled=secret.enabled,
        status=check.status.value, health_check=_health_check(check),
        keys=sorted(keys), missing_keys=sorted(expected - set(keys)),
    )
    return lambda: health


def prepare_dataset_resource_health(resource: ProjectDataset) -> Callable[[], ProjectDatasetHealthDTO]:
    dataset = prepare_dataset_health(resource.dataset)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    return lambda: ProjectDatasetHealthDTO(
        project_id=project_id, enabled=enabled, revoked=revoked, active=active, dataset=dataset()
    )


def prepare_secret_resource_health(resource: ProjectSecret) -> Callable[[], ProjectSecretHealthDTO]:
    secret = prepare_secret_health(resource.secret)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    return lambda: ProjectSecretHealthDTO(
        project_id=project_id, enabled=enabled, revoked=revoked, active=active, secret=secret()
    )


def prepare_trigger_resource_health(resource: ProjectTriggerRepository) -> Callable[[], ProjectTriggerRepositoryHealthDTO]:
    repository = prepare_repository_health(resource.trigger_repository)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    pr_count = PullRequestTrigger.query.filter_by(project_trigger_repository_id=resource.id).count()
    return lambda: ProjectTriggerRepositoryHealthDTO(
        project_id=project_id, pr_count=pr_count, enabled=enabled, revoked=revoked, active=active,
        trigger_repository=repository(),
    )


def prepare_results_resource_health(resource: ProjectResultsRepository) -> Callable[[], ProjectResultsRepositoryHealthDTO]:
    repository = prepare_repository_health(resource.results_repository)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    owned_by_federated_node, target_dir = resource.owned_by_federated_node, resource.target_dir
    return lambda: ProjectResultsRepositoryHealthDTO(
        project_id=project_id, owned_by_federated_node=owned_by_federated_node, target_dir=target_dir,
        enabled=enabled, revoked=revoked, active=active, results_repository=repository(),
    )


@router.get('/global/healthcheck', response_model=GlobalHealthDTO)
def global_healthcheck():
    """
    GET /global/healthcheck endpoint. Checks every global dataset, secret, trigger repository
    and results repository, in parallel. For development: it is as slow as the slowest of
    them, and lists them all.
    """
    datasets = [prepare_dataset_health(d) for d in Dataset.query.order_by(Dataset.id)]
    secrets = [prepare_secret_health(s) for s in Secret.query.order_by(Secret.id)]
    triggers = [prepare_repository_health(r) for r in TriggerRepository.query.order_by(TriggerRepository.id)]
    results_repositories = [prepare_repository_health(r) for r in ResultsRepository.query.order_by(ResultsRepository.id)]
    results = _run_all(datasets + secrets + triggers + results_repositories)

    end_datasets = len(datasets)
    end_secrets = end_datasets + len(secrets)
    end_triggers = end_secrets + len(triggers)
    health = GlobalHealthDTO(
        status="ok" if _is_ok(results) else "error",
        datasets=results[:end_datasets],
        secrets=results[end_datasets:end_secrets],
        trigger_repositories=results[end_secrets:end_triggers],
        results_repositories=results[end_triggers:],
    )
    return health


@router.get('/global/datasets/{dataset_id}/healthcheck', response_model=DatasetHealthDTO)
def dataset_healthcheck(dataset_id: int):
    """
    GET /global/datasets/<dataset_id>/healthcheck endpoint. Whether the node can connect to the
    dataset's database with its secret.
    """
    return prepare_dataset_health(Dataset.get_by_id(dataset_id))()


@router.get('/global/secrets/{label}/healthcheck', response_model=SecretHealthDTO)
def secret_healthcheck(label: str):
    """
    GET /global/secrets/<label>/healthcheck endpoint. Whether the secret is in its store with the
    keys its datasets and repositories need. Never the values.
    """
    return prepare_secret_health(_get_secret(label))()


@router.get('/global/providers/{provider_id}/healthcheck', response_model=GitProviderHealthDTO)
def provider_healthcheck(provider_id: int):
    """
    GET /global/providers/<provider_id>/healthcheck endpoint. Whether the provider's API answers.
    """
    return prepare_provider_health(GitProvider.get_by_id(provider_id))()


@router.get('/global/repositories/triggers/{repository_id}/healthcheck', response_model=RepositoryConnectionDTO)
def trigger_repository_healthcheck(repository_id: int):
    """
    GET /global/repositories/triggers/<repository_id>/healthcheck endpoint. Whether the repository
    can be reached with its own secret.
    """
    return prepare_repository_health(TriggerRepository.get_by_id(repository_id))()


@router.get('/global/repositories/results/{repository_id}/healthcheck', response_model=RepositoryConnectionDTO)
def results_repository_healthcheck(repository_id: int):
    """
    GET /global/repositories/results/<repository_id>/healthcheck endpoint. Whether the repository
    can be reached with its own secret.
    """
    return prepare_repository_health(ResultsRepository.get_by_id(repository_id))()


@router.get('/projects/{project_id}/healthcheck', response_model=ProjectHealthDTO)
def project_healthcheck(project_id: int):
    """
    GET /projects/<project_id>/healthcheck endpoint. Checks each trigger repository resource can be
    reached with its token, and reports its pull request count and the project's results
    repository. A failed check is reported in the body, still with a 200.
    """
    project = Project.get_by_id(project_id)

    trigger_resources = list(project.trigger_repository_assignments)
    results_resource = project.get_results_repository()
    prepared = [prepare_trigger_resource_health(resource) for resource in trigger_resources]
    if results_resource:
        prepared.append(prepare_results_resource_health(results_resource))
    results = _run_all(prepared)

    repositories = [
        RepositoryHealthDTO(
            id=resource.trigger_repository.id,
            uri=resource.trigger_repository.uri,
            provider=resource.trigger_repository.provider,
            pr_count=resource.pr_count,
            status=resource.trigger_repository.status,
            health_check=resource.trigger_repository.health_check,
        ) for resource in results[:len(trigger_resources)]
    ]

    results_health = None
    if results_resource:
        resource = results[-1]
        results_health = ResultsRepositoryHealthDTO(
            id=resource.results_repository.id,
            uri=resource.results_repository.uri,
            owned_by_federated_node=resource.owned_by_federated_node,
            target_dir=resource.target_dir,
            status=resource.results_repository.status,
            health_check=resource.results_repository.health_check,
        )

    healthy = repositories and _is_ok(repositories) and (results_health is None or _is_ok([results_health]))
    health = ProjectHealthDTO(
        id=project.id,
        name=project.name,
        enabled=project.enabled,
        status="ok" if healthy else "error",
        results_repository=results_health,
        trigger_repositories=repositories,
    )
    return health


@router.get('/projects/{project_id}/datasets/{dataset_id}/healthcheck', response_model=ProjectDatasetHealthDTO)
def project_dataset_healthcheck(project_id: int, dataset_id: int):
    """
    GET /projects/<project_id>/datasets/<dataset_id>/healthcheck endpoint. The global dataset's
    check and the project's resource state. 404 if the project has no resource for it.
    """
    return prepare_dataset_resource_health(_dataset_resource(project_id, dataset_id))()


@router.get('/projects/{project_id}/secrets/{label}/healthcheck', response_model=ProjectSecretHealthDTO)
def project_secret_healthcheck(project_id: int, label: str):
    """
    GET /projects/<project_id>/secrets/<label>/healthcheck endpoint. The global secret's check
    and the project's resource state. 404 if the project has no resource for it.
    """
    return prepare_secret_resource_health(_secret_resource(project_id, label))()


@router.get('/projects/{project_id}/repositories/triggers/{repository_id}/healthcheck', response_model=ProjectTriggerRepositoryHealthDTO)
def project_trigger_repository_healthcheck(project_id: int, repository_id: int):
    """
    GET /projects/<project_id>/repositories/triggers/<repository_id>/healthcheck endpoint. The
    global repository's check, the project's resource state and its pull request count. 404 if the
    project has no resource for it.
    """
    return prepare_trigger_resource_health(_trigger_resource(project_id, repository_id))()


@router.get('/projects/{project_id}/repositories/results/{repository_id}/healthcheck', response_model=ProjectResultsRepositoryHealthDTO)
def project_results_repository_healthcheck(project_id: int, repository_id: int):
    """
    GET /projects/<project_id>/repositories/results/<repository_id>/healthcheck endpoint. The
    global repository's check and the project's resource state. 404 if the project has no resource for it.
    """
    return prepare_results_resource_health(_results_resource(project_id, repository_id))()
