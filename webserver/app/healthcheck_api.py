"""
Healthcheck endpoints. A failed check is reported in the body, still with a 200. Nothing
returned includes a secret's value. Each resource has one check, run for the global
resource and for a project's link to it (which adds the link's state, and a 404 if the
project has none); the roll-ups are built from the same per-resource functions. Whatever
reads the database or the cluster happens in the request (the prepare_* functions), and
only the network calls run in the threads.
- GET /global/healthcheck, every global resource of the four kinds
- GET /global/datasets/<dataset_id>/healthcheck, can the node connect to its database
- GET /global/secrets/<label>/healthcheck, is it in its store with the keys its users need
- GET /global/providers/<provider_id>/healthcheck, does the git provider's API answer
- GET /global/repositories/triggers/<repository_id>/healthcheck
- GET /global/repositories/results/<repository_id>/healthcheck
- GET /projects/<project_id>/healthcheck, the project's trigger and results repository links
- GET /projects/<project_id>/datasets/<dataset_id>/healthcheck
- GET /projects/<project_id>/secrets/<label>/healthcheck
- GET /projects/<project_id>/repositories/triggers/<repository_id>/healthcheck
- GET /projects/<project_id>/repositories/results/<repository_id>/healthcheck
"""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

from flask import Blueprint

from app.dtos.healthcheck import (
    DatasetHealthDTO, GitProviderHealthDTO, GlobalHealthDTO, ProjectDatasetHealthDTO, ProjectResultsRepositoryHealthDTO,
    ProjectSecretHealthDTO, ProjectTriggerRepositoryHealthDTO, RepositoryConnectionDTO, SecretHealthDTO
)
from app.dtos.project import HealthCheckDTO, ProjectHealthDTO, RepositoryHealthDTO, ResultsRepositoryHealthDTO
from app.helpers.wrappers import audit, auth
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
from app.project_trigger_repositories_api import _assignment as _trigger_link
from app.projects_api import _dataset_link, _results_link, _secret_link
from app.secrets_api import SecretProvider, _get_secret

HEALTHCHECK_MAX_WORKERS = 8

bp = Blueprint('healthcheck', __name__)


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
    A secret nothing uses needs no particular key.
    """
    expected = set()
    if secret.datasets:
        expected |= set(Dataset.SECRET_KEYS)
    if secret.trigger_repositories or secret.results_repositories:
        expected |= set(GitRepositoryMixin.SECRET_KEYS)
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


def prepare_dataset_link_health(link: ProjectDataset) -> Callable[[], ProjectDatasetHealthDTO]:
    dataset = prepare_dataset_health(link.dataset)
    project_id, enabled, revoked, active = link.project_id, link.enabled, link.revoked, link.active
    return lambda: ProjectDatasetHealthDTO(
        project_id=project_id, enabled=enabled, revoked=revoked, active=active, dataset=dataset()
    )


def prepare_secret_link_health(link: ProjectSecret) -> Callable[[], ProjectSecretHealthDTO]:
    secret = prepare_secret_health(link.secret)
    project_id, enabled, revoked, active = link.project_id, link.enabled, link.revoked, link.active
    return lambda: ProjectSecretHealthDTO(
        project_id=project_id, enabled=enabled, revoked=revoked, active=active, secret=secret()
    )


def prepare_trigger_link_health(link: ProjectTriggerRepository) -> Callable[[], ProjectTriggerRepositoryHealthDTO]:
    repository = prepare_repository_health(link.trigger_repository)
    project_id, enabled, revoked, active = link.project_id, link.enabled, link.revoked, link.active
    pr_count = PullRequestTrigger.query.filter_by(project_trigger_repository_id=link.id).count()
    return lambda: ProjectTriggerRepositoryHealthDTO(
        project_id=project_id, pr_count=pr_count, enabled=enabled, revoked=revoked, active=active,
        trigger_repository=repository(),
    )


def prepare_results_link_health(link: ProjectResultsRepository) -> Callable[[], ProjectResultsRepositoryHealthDTO]:
    repository = prepare_repository_health(link.results_repository)
    project_id, enabled, revoked, active = link.project_id, link.enabled, link.revoked, link.active
    owned_by_federated_node, target_dir = link.owned_by_federated_node, link.target_dir
    return lambda: ProjectResultsRepositoryHealthDTO(
        project_id=project_id, owned_by_federated_node=owned_by_federated_node, target_dir=target_dir,
        enabled=enabled, revoked=revoked, active=active, results_repository=repository(),
    )


@bp.route('/global/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
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
    return health.dump(), HTTPStatus.OK


@bp.route('/global/datasets/<int:dataset_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def dataset_healthcheck(dataset_id: int):
    """
    GET /global/datasets/<dataset_id>/healthcheck endpoint. Whether the node can connect to the
    dataset's database with its secret.
    """
    return prepare_dataset_health(Dataset.get_by_id(dataset_id))().dump(), HTTPStatus.OK


@bp.route('/global/secrets/<label>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def secret_healthcheck(label: str):
    """
    GET /global/secrets/<label>/healthcheck endpoint. Whether the secret is in its store with the
    keys its datasets and repositories need. Never the values.
    """
    return prepare_secret_health(_get_secret(label))().dump(), HTTPStatus.OK


@bp.route('/global/providers/<int:provider_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def provider_healthcheck(provider_id: int):
    """
    GET /global/providers/<provider_id>/healthcheck endpoint. Whether the provider's API answers.
    """
    return prepare_provider_health(GitProvider.get_by_id(provider_id))().dump(), HTTPStatus.OK


@bp.route('/global/repositories/triggers/<int:repository_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def trigger_repository_healthcheck(repository_id: int):
    """
    GET /global/repositories/triggers/<repository_id>/healthcheck endpoint. Whether the repository
    can be reached with its own secret.
    """
    return prepare_repository_health(TriggerRepository.get_by_id(repository_id))().dump(), HTTPStatus.OK


@bp.route('/global/repositories/results/<int:repository_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def results_repository_healthcheck(repository_id: int):
    """
    GET /global/repositories/results/<repository_id>/healthcheck endpoint. Whether the repository
    can be reached with its own secret.
    """
    return prepare_repository_health(ResultsRepository.get_by_id(repository_id))().dump(), HTTPStatus.OK


@bp.route('/projects/<int:project_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_healthcheck(project_id: int):
    """
    GET /projects/<project_id>/healthcheck endpoint. Checks each trigger repository link can be
    reached with its token, and reports its pull request count and the project's results
    repository. A failed check is reported in the body, still with a 200.
    """
    project = Project.get_by_id(project_id)

    trigger_links = list(project.trigger_repository_assignments)
    results_link = project.get_results_repository()
    prepared = [prepare_trigger_link_health(link) for link in trigger_links]
    if results_link:
        prepared.append(prepare_results_link_health(results_link))
    results = _run_all(prepared)

    repositories = [
        RepositoryHealthDTO(
            id=link.trigger_repository.id,
            uri=link.trigger_repository.uri,
            provider=link.trigger_repository.provider,
            pr_count=link.pr_count,
            status=link.trigger_repository.status,
            health_check=link.trigger_repository.health_check,
        ) for link in results[:len(trigger_links)]
    ]

    results_health = None
    if results_link:
        link = results[-1]
        results_health = ResultsRepositoryHealthDTO(
            id=link.results_repository.id,
            uri=link.results_repository.uri,
            owned_by_federated_node=link.owned_by_federated_node,
            target_dir=link.target_dir,
            status=link.results_repository.status,
            health_check=link.results_repository.health_check,
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
    return health.dump(), HTTPStatus.OK


@bp.route('/projects/<int:project_id>/datasets/<int:dataset_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_dataset_healthcheck(project_id: int, dataset_id: int):
    """
    GET /projects/<project_id>/datasets/<dataset_id>/healthcheck endpoint. The global dataset's
    check and the project's link state. 404 if the project has no link to it.
    """
    return prepare_dataset_link_health(_dataset_link(project_id, dataset_id))().dump(), HTTPStatus.OK


@bp.route('/projects/<int:project_id>/secrets/<label>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_secret_healthcheck(project_id: int, label: str):
    """
    GET /projects/<project_id>/secrets/<label>/healthcheck endpoint. The global secret's check
    and the project's link state. 404 if the project has no link to it.
    """
    return prepare_secret_link_health(_secret_link(project_id, label))().dump(), HTTPStatus.OK


@bp.route('/projects/<int:project_id>/repositories/triggers/<int:repository_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_trigger_repository_healthcheck(project_id: int, repository_id: int):
    """
    GET /projects/<project_id>/repositories/triggers/<repository_id>/healthcheck endpoint. The
    global repository's check, the project's link state and its pull request count. 404 if the
    project has no link to it.
    """
    return prepare_trigger_link_health(_trigger_link(project_id, repository_id))().dump(), HTTPStatus.OK


@bp.route('/projects/<int:project_id>/repositories/results/<int:repository_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_results_repository_healthcheck(project_id: int, repository_id: int):
    """
    GET /projects/<project_id>/repositories/results/<repository_id>/healthcheck endpoint. The
    global repository's check and the project's link state. 404 if the project has no link to it.
    """
    return prepare_results_link_health(_results_link(project_id, repository_id))().dump(), HTTPStatus.OK
