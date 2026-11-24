"""
Healthcheck endpoints. A failed check is reported in the body, still with a 200. Nothing returned includes a
secret's value. The checks are in app/health/; each resource's own healthcheck route is in its router.
On probes_router, which needs no token (OPEN_ROUTERS):
- GET /, redirects to /health_check
- GET /ready_check, the server has started
- GET /health_check, can the node reach Keycloak
The roll-ups, built from the same per-resource checks:
- GET /global/healthcheck, every global resource of the four kinds
- GET /projects/<project_id>/healthcheck, the project's trigger and results repository resources
"""
from http import HTTPStatus

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
from fednode.clients.keycloak.login import KeycloakLogin
from fednode.http import ClientError

from app.settings import settings
from app.dtos import healthcheck
from app.dtos import project as project_dtos
from app.health.datasets import prepare_dataset_health
from app.health.repositories import (
    prepare_repository_health, prepare_results_resource_health, prepare_trigger_resource_health
)
from app.health.run import is_ok, run_all
from app.health.secrets import prepare_secret_health
from app.models.dataset import Dataset
from app.models.project import Project
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret
from app.models.trigger_repository import TriggerRepository

probes_router = APIRouter(tags=["healthcheck"])
router = APIRouter(tags=["healthcheck"])


@probes_router.get('/', include_in_schema=False)
def index():
    """
    GET / endpoint.
        Redirects to /health_check
    """
    return RedirectResponse('/health_check', status_code=HTTPStatus.FOUND)


@probes_router.get("/ready_check")
def ready_check() -> dict:
    """
    GET /ready_check endpoint
        Mostly to tell k8s the server has started
    """
    return {"status": "ready"}


@probes_router.get(
    "/health_check", response_model=healthcheck.NodeHealthDTO, responses={HTTPStatus.BAD_GATEWAY: {"model": healthcheck.NodeHealthDTO}}
)
def health_check():
    """
    GET /health_check endpoint
        Checks the connection to keycloak and returns a jsonized summary
    """
    try:
        kc_request = KeycloakLogin(
            settings.services.keycloak.url, "master", timeout=(settings.http.connect_timeout, settings.http.read_timeout)
        ).realm_info()
        kc_status = kc_request.ok
        status_text = "ok" if kc_request.ok else "non operational"
        code = HTTPStatus.OK if kc_request.ok else HTTPStatus.BAD_GATEWAY
    except ClientError:
        kc_status = False
        status_text = "non operational"
        code = HTTPStatus.BAD_GATEWAY

    return JSONResponse({"status": status_text, "keycloak": kc_status}, status_code=code)


@router.get('/global/healthcheck', response_model=healthcheck.GlobalHealthDTO)
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
    results = run_all(datasets + secrets + triggers + results_repositories)

    end_datasets = len(datasets)
    end_secrets = end_datasets + len(secrets)
    end_triggers = end_secrets + len(triggers)
    health = healthcheck.GlobalHealthDTO(
        status="ok" if is_ok(results) else "error",
        datasets=results[:end_datasets],
        secrets=results[end_datasets:end_secrets],
        trigger_repositories=results[end_secrets:end_triggers],
        results_repositories=results[end_triggers:],
    )
    return health


@router.get('/projects/{project_id}/healthcheck', response_model=project_dtos.ProjectHealthDTO)
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
    results = run_all(prepared)

    repositories = [
        project_dtos.RepositoryHealthDTO(
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
        results_health = project_dtos.ResultsRepositoryHealthDTO(
            id=resource.results_repository.id,
            uri=resource.results_repository.uri,
            owned_by_federated_node=resource.owned_by_federated_node,
            target_dir=resource.target_dir,
            base_branch=resource.base_branch,
            status=resource.results_repository.status,
            health_check=resource.results_repository.health_check,
        )

    healthy = repositories and is_ok(repositories) and (results_health is None or is_ok([results_health]))
    health = project_dtos.ProjectHealthDTO(
        id=project.id,
        name=project.name,
        enabled=project.enabled,
        status="ok" if healthy else "error",
        results_repository=results_health,
        trigger_repositories=repositories,
    )
    return health
