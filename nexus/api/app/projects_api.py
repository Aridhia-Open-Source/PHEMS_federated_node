"""
project endpoints:
- GET /projects
- GET /projects/<project_id>
- POST /projects
- PATCH /projects/<project_id>
- DELETE /projects/<project_id>
- GET /projects/<project_id>/healthcheck, see healthcheck_api.py

A project's resources, its rows for the global resources (datasets, secrets, results repositories; the
trigger repositories are in project_trigger_repositories_api.py). A project resource is addressed by the
global resource's id (a secret's label), never by the project resource row's. Projects create no global resource:
PUT assigns one that exists, 201 the first time and 200 after, replacing the project's settings,
PATCH changes some of them, DELETE unassigns. `revoked` is the controller's, so only PATCH sets
it, admin only.
- GET /projects/<project_id>/datasets
- GET|PUT|PATCH|DELETE /projects/<project_id>/datasets/<dataset_id>
- GET /projects/<project_id>/secrets
- GET|PUT|PATCH|DELETE /projects/<project_id>/secrets/{label}
- GET /projects/<project_id>/repositories/results
- GET|PUT|PATCH|DELETE /projects/<project_id>/repositories/results/<repository_id>
"""

from http import HTTPStatus
from fastapi import APIRouter, Body, Depends, Response

from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, UnauthorizedError
from app.dtos.base import PageDTO, page_of
from app.dtos.dataset import ProjectDatasetDTO
from app.dtos.results_repository import ProjectResultsRepositoryDTO
from app.dtos.secret import ProjectSecretDTO
from app.dtos.project import ProjectCreatedDTO, ProjectDTO, ProjectRequest
from app.helpers.project_state import require_disabled
from app.helpers.pull_request_fanout import backfill, skip_gap
from app.helpers.repository_loop import check_no_loop, normalise_dir
from app.helpers.query_filters import QueryFilters, parse_query_params
from app.helpers.wrappers import Caller, get_caller, require_scope
from app.models.dataset import Dataset
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret


router = APIRouter(prefix='/projects', tags=["projects"], dependencies=[Depends(require_scope('can_admin_dataset'))])


@router.get('/', response_model=PageDTO[ProjectDTO])
@router.get('', response_model=PageDTO[ProjectDTO])
def list_projects(filters: QueryFilters = Depends()):
    """
    GET /projects endpoint.
    """
    return page_of(parse_query_params(Project, filters.copy()), ProjectDTO)


@router.get('/{project_id}', response_model=ProjectDTO)
def project_by_id(project_id: int):
    """
    GET /projects/<project_id> endpoint.
    """
    project = Project.query.filter_by(id=project_id).one_or_none()
    if project is None:
        raise DBRecordNotFoundError("Project not found")
    return ProjectDTO.from_model(project)


@router.post('/', status_code=HTTPStatus.CREATED, response_model=ProjectCreatedDTO)
@router.post('', status_code=HTTPStatus.CREATED, response_model=ProjectCreatedDTO)
def create_project(req: ProjectRequest):
    """
    POST /projects endpoint.
    """
    body = req.model_dump(exclude_unset=True)
    if Project.query.filter(Project.name == body["name"]).one_or_none():
        raise InvalidRequest(f"Project {body["name"]} already exists", HTTPStatus.CONFLICT)

    project = Project(**body)
    project.add()
    return {"id": project.id}


@router.patch('/{project_id}', response_model=ProjectDTO)
def patch_project(project_id: int, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /projects/<project_id> endpoint. Enables or disables the project. Turning the project
    on again skips the gap: what was merged while it was off gets no trigger. With
    `"backfill": true` it creates those triggers instead. `backfill` is only for enabling a
    disabled project (`"enabled": true`), otherwise a 400, and is not stored.
    `revoked` (a boolean, admin only) withdraws the project, or restores it, and does not change `enabled`:
    while it is revoked its tasks fail, nothing is delivered and no pull request gets a trigger
    (see helpers/task_config.revoked_resources). Restoring it skips the gap like enabling does.
    """
    project = Project.get_by_id(project_id)

    fields = {"enabled", "backfill", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a project")
    if "backfill" in body and (body.get("enabled") is not True or project.enabled):
        raise InvalidRequest("backfill is only valid with enabled: true on a disabled project")

    was_revoked = project.revoked
    if "revoked" in body:
        project.revoked = body["revoked"]
    if body.get("enabled") and not project.enabled:
        project.enabled = True
        if body.get("backfill"):
            backfill(project.trigger_repository_assignments)
        else:
            skip_gap(project.trigger_repository_assignments)
    else:
        if "enabled" in body:
            project.enabled = body["enabled"]
        if was_revoked and not project.revoked:
            skip_gap(project.trigger_repository_assignments)
    db.session.commit()
    return ProjectDTO.from_model(project)


@router.delete('/{project_id}', status_code=HTTPStatus.NO_CONTENT)
def delete_project(project_id: int):
    """
    DELETE /projects/<project_id> endpoint. Soft deletes the project and revokes and deletes
    every project resource under it: datasets, secrets, results repository and trigger repositories. Its tasks
    and triggers stay. Secrets, datasets and results repositories belong to no project: they, and
    their stored values, are left alone.
    """
    project = Project.get_by_id(project_id)
    for resource in (
        *project.dataset_assignments, *project.secret_assignments,
        *project.trigger_repository_assignments, *project.results_repository_assignments,
    ):
        resource.soft_delete()
    project.soft_delete()
    db.session.commit()


def _resource(model, project_id: int, resource_id: int, what: str):
    """The project's resource for a global resource, found by the global resource's id."""
    column = {ProjectDataset: ProjectDataset.dataset_id, ProjectSecret: ProjectSecret.secret_id,
              ProjectResultsRepository: ProjectResultsRepository.results_repository_id}[model]
    resource = model.query.filter(model.project_id == project_id, column == resource_id).one_or_none()
    if resource is None:
        raise DBRecordNotFoundError(f"{what} is not assigned to project {project_id}")
    return resource


def _enabled(body: dict) -> bool:
    if not isinstance(body.get("enabled", True), bool):
        raise InvalidRequest("enabled must be a boolean")
    return body.get("enabled", True)


def _dataset_resource(project_id: int, dataset_id: int) -> ProjectDataset:
    return _resource(ProjectDataset, project_id, dataset_id, f"Dataset {dataset_id}")


@router.get('/{project_id}/datasets', response_model=list[ProjectDatasetDTO])
def list_project_datasets(project_id: int):
    """
    GET /projects/<project_id>/datasets endpoint. The project's dataset resources, inactive
    ones included with their flags.
    """
    Project.get_by_id(project_id)
    resources = ProjectDataset.query.filter_by(project_id=project_id).order_by(ProjectDataset.id)
    return [ProjectDatasetDTO.from_model(a) for a in resources]


@router.get('/{project_id}/datasets/{dataset_id}', response_model=ProjectDatasetDTO)
def get_project_dataset(project_id: int, dataset_id: int):
    """
    GET /projects/<project_id>/datasets/<dataset_id> endpoint. The dataset is the global one's id.
    """
    return ProjectDatasetDTO.from_model(_dataset_resource(project_id, dataset_id))


@router.put('/{project_id}/datasets/{dataset_id}', response_model=ProjectDatasetDTO)
def put_project_dataset(project_id: int, dataset_id: int, response: Response, body: dict = Body(default_factory=dict)):
    """
    PUT /projects/<project_id>/datasets/<dataset_id> endpoint. Assigns a global dataset to the
    project, 201, and replaces the project's settings if it is assigned already, 200. The first one assigned becomes the project's default.
    Body: {"enabled": true}, optional.
    """
    project = Project.get_by_id(project_id)
    if not set(body) <= {"enabled"}:
        raise InvalidRequest("Provide, optionally, enabled")
    enabled = _enabled(body)
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id)

    resource = ProjectDataset.query.filter_by(project_id=project.id, dataset_id=dataset.id).one_or_none()
    if resource is None:
        resource = ProjectDataset(project.id, dataset.id, enabled=enabled)
        resource.add()
        response.status_code = HTTPStatus.CREATED
        return ProjectDatasetDTO.from_model(resource)

    resource.enabled = enabled
    db.session.commit()
    return ProjectDatasetDTO.from_model(resource)


@router.patch('/{project_id}/datasets/{dataset_id}', response_model=ProjectDatasetDTO)
def patch_project_dataset(project_id: int, dataset_id: int, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /projects/<project_id>/datasets/<dataset_id> endpoint. Turns the project resource on or
    off (enabled), or revokes and re-grants it (revoked), which is admin only and takes effect at once.
    """
    resource = _dataset_resource(project_id, dataset_id)
    fields = {"enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")

    for field in body:
        setattr(resource, field, body[field])
    db.session.commit()
    return ProjectDatasetDTO.from_model(resource)


@router.delete('/{project_id}/datasets/{dataset_id}', status_code=HTTPStatus.NO_CONTENT)
def delete_project_dataset(project_id: int, dataset_id: int):
    """
    DELETE /projects/<project_id>/datasets/<dataset_id> endpoint. Unassigns the dataset, not the
    dataset itself: a soft delete that also revokes the project resource. If it was the project's default,
    the project has none afterwards.
    """
    resource = _dataset_resource(project_id, dataset_id)
    resource.soft_delete()
    db.session.commit()


def _secret_resource(project_id: int, label: str) -> ProjectSecret:
    secret = Secret.query.filter_by(label=label).one_or_none()
    if secret is None:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")
    return _resource(ProjectSecret, project_id, secret.id, f"Secret {label}")


@router.get('/{project_id}/secrets', response_model=list[ProjectSecretDTO])
def list_project_secrets(project_id: int):
    """
    GET /projects/<project_id>/secrets endpoint. The project's secret resources, inactive ones
    included with their flags. References only, never the values.
    """
    Project.get_by_id(project_id)
    resources = ProjectSecret.query.filter_by(project_id=project_id).order_by(ProjectSecret.id)
    return [ProjectSecretDTO.from_model(a) for a in resources]


@router.get('/{project_id}/secrets/{label}', response_model=ProjectSecretDTO)
def get_project_secret(project_id: int, label: str):
    """
    GET /projects/<project_id>/secrets/{label} endpoint.
    """
    return ProjectSecretDTO.from_model(_secret_resource(project_id, label))


@router.put('/{project_id}/secrets/{label}', response_model=ProjectSecretDTO)
def put_project_secret(project_id: int, label: str, response: Response, body: dict = Body(default_factory=dict)):
    """
    PUT /projects/<project_id>/secrets/{label} endpoint. Assigns a global secret to the project,
    201, and replaces the project's settings if it is assigned already, 200.
    Body: {"enabled": true}, optional.
    """
    project = Project.get_by_id(project_id)
    if not set(body) <= {"enabled"}:
        raise InvalidRequest("Provide, optionally, enabled")
    enabled = _enabled(body)
    secret = Secret.query.filter_by(label=label).one_or_none()
    if secret is None:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")

    resource = ProjectSecret.query.filter_by(project_id=project.id, secret_id=secret.id).one_or_none()
    if resource is None:
        resource = ProjectSecret(project.id, secret.id, enabled=enabled)
        resource.add()
        response.status_code = HTTPStatus.CREATED
        return ProjectSecretDTO.from_model(resource)

    resource.enabled = enabled
    db.session.commit()
    return ProjectSecretDTO.from_model(resource)


@router.patch('/{project_id}/secrets/{label}', response_model=ProjectSecretDTO)
def patch_project_secret(project_id: int, label: str, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /projects/<project_id>/secrets/{label} endpoint. Turns the project resource on or off (enabled),
    or revokes and re-grants it (revoked), which is admin only and takes effect at once.
    """
    resource = _secret_resource(project_id, label)
    fields = {"enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a secret")

    for field in body:
        setattr(resource, field, body[field])
    db.session.commit()
    return ProjectSecretDTO.from_model(resource)


@router.delete('/{project_id}/secrets/{label}', status_code=HTTPStatus.NO_CONTENT)
def delete_project_secret(project_id: int, label: str):
    """
    DELETE /projects/<project_id>/secrets/{label} endpoint. Unassigns the secret, not the secret
    itself: a soft delete that also revokes the project resource.
    """
    resource = _secret_resource(project_id, label)
    resource.soft_delete()
    db.session.commit()


def _results_resource(project_id: int, repository_id: int) -> ProjectResultsRepository:
    return _resource(ProjectResultsRepository, project_id, repository_id, f"Results repository {repository_id}")


def _check_results_loop(assignment: ProjectResultsRepository):
    """Refuses the change, rolling it back, if the results would land where a trigger watches."""
    try:
        check_no_loop(assignment.results_repository.provider_id, assignment.results_repository.repo_path)
    except InvalidRequest:
        db.session.rollback()
        raise


@router.get('/{project_id}/repositories/results', response_model=list[ProjectResultsRepositoryDTO])
def list_project_results_repositories(project_id: int):
    """
    GET /projects/<project_id>/repositories/results endpoint. The project's results repository
    resource, an inactive one included with its flags, so a project always lists exactly one.
    """
    Project.get_by_id(project_id)
    resources = ProjectResultsRepository.query.filter_by(project_id=project_id).order_by(ProjectResultsRepository.id)
    return [ProjectResultsRepositoryDTO.from_model(a) for a in resources]


@router.get('/{project_id}/repositories/results/{repository_id}', response_model=ProjectResultsRepositoryDTO)
def get_project_results_repository(project_id: int, repository_id: int):
    """
    GET /projects/<project_id>/repositories/results/<repository_id> endpoint. The repository is the global one's id.
    """
    return ProjectResultsRepositoryDTO.from_model(_results_resource(project_id, repository_id))


@router.put('/{project_id}/repositories/results/{repository_id}', response_model=ProjectResultsRepositoryDTO)
def put_project_results_repository(
    project_id: int, repository_id: int, response: Response, body: dict = Body(default_factory=dict)
):
    """
    PUT /projects/<project_id>/repositories/results/<repository_id> endpoint. Assigns a global
    results repository to the project, which has one, 201, and replaces the project's settings
    if it is assigned already, 200. Assigning needs the project disabled. A change of target_dir
    is caught by the configuration snapshot of the tasks created before, which then fail
    instead of delivering there.
    Body: {"target_dir": "results", "owned_by_federated_node": true, "enabled": true}, the last
    two are optional.
    """
    project = Project.get_by_id(project_id)
    if not set(body) <= {"target_dir", "owned_by_federated_node", "enabled"} or not body.get("target_dir"):
        raise InvalidRequest("Provide target_dir and, optionally, owned_by_federated_node and enabled")
    for field in ("owned_by_federated_node", "enabled"):
        if not isinstance(body.get(field, True), bool):
            raise InvalidRequest(f"{field} must be a boolean")
    target_dir = normalise_dir(body["target_dir"])
    if not target_dir:
        raise InvalidRequest("target_dir is required")

    repo = ResultsRepository.get_by_id(repository_id)
    resource = ProjectResultsRepository.query.filter_by(project_id=project.id).first()
    if resource and resource.results_repository_id != repo.id:
        raise InvalidRequest(f"Project {project.id} already has a results repository", HTTPStatus.CONFLICT)
    if resource is None:
        require_disabled(project)

    created = resource is None
    if created:
        resource = ProjectResultsRepository(project.id, repo.id, target_dir)
        resource.add(commit=False)
    resource.target_dir = target_dir
    resource.owned_by_federated_node = body.get("owned_by_federated_node", True)
    resource.enabled = body.get("enabled", True)
    db.session.flush()
    _check_results_loop(resource)
    db.session.commit()
    response.status_code = HTTPStatus.CREATED if created else HTTPStatus.OK
    return ProjectResultsRepositoryDTO.from_model(resource)


@router.patch('/{project_id}/repositories/results/{repository_id}', response_model=ProjectResultsRepositoryDTO)
def patch_project_results_repository(project_id: int, repository_id: int, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /projects/<project_id>/repositories/results/<repository_id> endpoint. Changes where
    the project's results go (target_dir, owned_by_federated_node), at any time (the tasks created
    before fail instead of delivering to the new place), or turns the project resource on or
    off (enabled), or revokes and re-grants it
    (revoked), which is admin only and takes effect at once.
    """
    resource = _results_resource(project_id, repository_id)
    fields = {"target_dir", "owned_by_federated_node", "enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body.keys() - {"target_dir"}:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a results repository")

    if "target_dir" in body:
        target_dir = normalise_dir(body["target_dir"] or "")
        if not target_dir:
            raise InvalidRequest("target_dir cannot be empty")
        body["target_dir"] = target_dir
    for field in body:
        setattr(resource, field, body[field])
    db.session.flush()
    _check_results_loop(resource)
    db.session.commit()
    return ProjectResultsRepositoryDTO.from_model(resource)


@router.delete('/{project_id}/repositories/results/{repository_id}', status_code=HTTPStatus.NO_CONTENT)
def delete_project_results_repository(project_id: int, repository_id: int):
    """
    DELETE /projects/<project_id>/repositories/results/<repository_id> endpoint. Unassigns the
    repository, not the repository itself: a soft delete that also revokes the project resource. A task of the
    project still in flight gets a REVOKED result.
    """
    resource = _results_resource(project_id, repository_id)
    resource.soft_delete()
    db.session.commit()
