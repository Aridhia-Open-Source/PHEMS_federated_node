"""
project endpoints:
- GET /projects
- GET /projects/<project_id>
- POST /projects
- PATCH /projects/<project_id>
- DELETE /projects/<project_id>
- GET /projects/<project_id>/healthcheck, see healthcheck_api.py

A project's links to the global resources (datasets, secrets, results repositories; the
trigger repositories are in project_trigger_repositories_api.py). A link is addressed by the
global resource's id (a secret's label), never by the link row's. Projects create no resource:
PUT links one that exists, 201 the first time and 200 after, replacing the project's settings,
PATCH changes some of them, DELETE unlinks. `revoked` is the controller's, so only PATCH sets
it, admin only.
- GET /projects/<project_id>/datasets
- GET|PUT|PATCH|DELETE /projects/<project_id>/datasets/<dataset_id>
- GET /projects/<project_id>/secrets
- GET|PUT|PATCH|DELETE /projects/<project_id>/secrets/<label>
- GET /projects/<project_id>/repositories/results
- GET|PUT|PATCH|DELETE /projects/<project_id>/repositories/results/<repository_id>
"""

from http import HTTPStatus
from flask import Blueprint, g, request

from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, UnauthorizedError
from app.dtos.base import page_of
from app.dtos.dataset import ProjectDatasetDTO
from app.dtos.results_repository import ProjectResultsRepositoryDTO
from app.dtos.secret import ProjectSecretDTO
from app.dtos.project import ProjectDTO, ProjectRequest
from app.helpers.project_lock import require_locked
from app.helpers.pull_request_fanout import skip_gap
from app.helpers.repository_loop import check_no_loop, normalise_dir
from app.helpers.query_filters import parse_query_params
from app.helpers.wrappers import audit, auth
from app.models.dataset import Dataset
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret


bp = Blueprint('projects', __name__, url_prefix='/projects')


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_projects():
    """
    GET /projects endpoint.
    """
    return page_of(parse_query_params(Project, request.args.copy()), ProjectDTO), HTTPStatus.OK


@bp.route('/<int:project_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_by_id(project_id: int):
    """
    GET /projects/<project_id> endpoint.
    """
    project = Project.query.filter_by(id=project_id).one_or_none()
    if project is None:
        raise DBRecordNotFoundError("Project not found")
    return ProjectDTO.from_model(project).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def create_project():
    """
    POST /projects endpoint.
    """
    body = ProjectRequest.parse(request.json).model_dump(exclude_unset=True)
    if Project.query.filter(Project.name == body["name"]).one_or_none():
        raise InvalidRequest(f"Project {body["name"]} already exists", HTTPStatus.CONFLICT)

    project = Project(**body)
    project.add()
    return {"id": project.id}, HTTPStatus.CREATED


@bp.route('/<int:project_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project(project_id: int):
    """
    PATCH /projects/<project_id> endpoint. Enables or disables the project, locks or unlocks
    it. Neither needs a lock. Turning the project on again skips the gap: what was merged while it
    was off gets no trigger.
    """
    project = Project.get_by_id(project_id)

    body = request.json or {}
    fields = {"enabled", "locked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")

    if body.get("enabled") and not project.enabled:
        skip_gap(project.trigger_repository_assignments)
    for field in body:
        setattr(project, field, body[field])
    db.session.commit()
    return ProjectDTO.from_model(project).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project(project_id: int):
    """
    DELETE /projects/<project_id> endpoint. Soft deletes the project and revokes and deletes
    every link under it: datasets, secrets, results repository and trigger repositories. Its tasks
    and triggers stay. Secrets, datasets and results repositories belong to no project: they, and
    their stored values, are left alone.
    """
    project = Project.get_by_id(project_id)
    for link in (
        *project.dataset_assignments, *project.secret_assignments,
        *project.trigger_repository_assignments, *project.results_repository_assignments,
    ):
        link.soft_delete()
    project.soft_delete()
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


def _link(model, project_id: int, resource_id: int, what: str):
    """The project's link to a global resource, found by the resource's id."""
    column = {ProjectDataset: ProjectDataset.dataset_id, ProjectSecret: ProjectSecret.secret_id,
              ProjectResultsRepository: ProjectResultsRepository.results_repository_id}[model]
    link = model.query.filter(model.project_id == project_id, column == resource_id).one_or_none()
    if link is None:
        raise DBRecordNotFoundError(f"{what} is not linked to project {project_id}")
    return link


def _enabled(body: dict) -> bool:
    if not isinstance(body.get("enabled", True), bool):
        raise InvalidRequest("enabled must be a boolean")
    return body.get("enabled", True)


def _dataset_link(project_id: int, dataset_id: int) -> ProjectDataset:
    return _link(ProjectDataset, project_id, dataset_id, f"Dataset {dataset_id}")


@bp.route('/<int:project_id>/datasets', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_project_datasets(project_id: int):
    """
    GET /projects/<project_id>/datasets endpoint. The project's dataset links, inactive
    ones included with their flags.
    """
    Project.get_by_id(project_id)
    links = ProjectDataset.query.filter_by(project_id=project_id).order_by(ProjectDataset.id)
    return [ProjectDatasetDTO.from_model(a).dump() for a in links], HTTPStatus.OK


@bp.route('/<int:project_id>/datasets/<int:dataset_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_project_dataset(project_id: int, dataset_id: int):
    """
    GET /projects/<project_id>/datasets/<dataset_id> endpoint. The dataset is the global one's id.
    """
    return ProjectDatasetDTO.from_model(_dataset_link(project_id, dataset_id)).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/datasets/<int:dataset_id>', methods=['PUT'])
@audit
@auth(scope='can_admin_dataset')
def put_project_dataset(project_id: int, dataset_id: int):
    """
    PUT /projects/<project_id>/datasets/<dataset_id> endpoint. Links a global dataset to the
    project, 201, and replaces the project's settings if it is linked already, 200. The first one linked becomes the project's default.
    Body: {"enabled": true}, optional.
    """
    project = Project.get_by_id(project_id)
    body = request.json or {}
    if not set(body) <= {"enabled"}:
        raise InvalidRequest("Provide, optionally, enabled")
    enabled = _enabled(body)
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id)

    link = ProjectDataset.query.filter_by(project_id=project.id, dataset_id=dataset.id).one_or_none()
    if link is None:
        link = ProjectDataset(project.id, dataset.id, enabled=enabled)
        link.add()
        return ProjectDatasetDTO.from_model(link).dump(), HTTPStatus.CREATED

    link.enabled = enabled
    db.session.commit()
    return ProjectDatasetDTO.from_model(link).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/datasets/<int:dataset_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_dataset(project_id: int, dataset_id: int):
    """
    PATCH /projects/<project_id>/datasets/<dataset_id> endpoint. Turns the link on or
    off (enabled), or revokes and re-grants it (revoked), which is admin only and takes effect at once.
    """
    link = _dataset_link(project_id, dataset_id)
    body = request.json or {}
    fields = {"enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")

    for field in body:
        setattr(link, field, body[field])
    db.session.commit()
    return ProjectDatasetDTO.from_model(link).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/datasets/<int:dataset_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project_dataset(project_id: int, dataset_id: int):
    """
    DELETE /projects/<project_id>/datasets/<dataset_id> endpoint. Unlinks the dataset, not the
    dataset itself: a soft delete that also revokes the link. If it was the project's default,
    the project has none afterwards.
    """
    link = _dataset_link(project_id, dataset_id)
    link.soft_delete()
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


def _secret_link(project_id: int, label: str) -> ProjectSecret:
    secret = Secret.query.filter_by(label=label).one_or_none()
    if secret is None:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")
    return _link(ProjectSecret, project_id, secret.id, f"Secret {label}")


@bp.route('/<int:project_id>/secrets', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_project_secrets(project_id: int):
    """
    GET /projects/<project_id>/secrets endpoint. The project's secret links, inactive ones
    included with their flags. References only, never the values.
    """
    Project.get_by_id(project_id)
    links = ProjectSecret.query.filter_by(project_id=project_id).order_by(ProjectSecret.id)
    return [ProjectSecretDTO.from_model(a).dump() for a in links], HTTPStatus.OK


@bp.route('/<int:project_id>/secrets/<label>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_project_secret(project_id: int, label: str):
    """
    GET /projects/<project_id>/secrets/<label> endpoint.
    """
    return ProjectSecretDTO.from_model(_secret_link(project_id, label)).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/secrets/<label>', methods=['PUT'])
@audit
@auth(scope='can_admin_dataset')
def put_project_secret(project_id: int, label: str):
    """
    PUT /projects/<project_id>/secrets/<label> endpoint. Links a global secret to the project,
    201, and replaces the project's settings if it is linked already, 200.
    Body: {"enabled": true}, optional.
    """
    project = Project.get_by_id(project_id)
    body = request.json or {}
    if not set(body) <= {"enabled"}:
        raise InvalidRequest("Provide, optionally, enabled")
    enabled = _enabled(body)
    secret = Secret.query.filter_by(label=label).one_or_none()
    if secret is None:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")

    link = ProjectSecret.query.filter_by(project_id=project.id, secret_id=secret.id).one_or_none()
    if link is None:
        link = ProjectSecret(project.id, secret.id, enabled=enabled)
        link.add()
        return ProjectSecretDTO.from_model(link).dump(), HTTPStatus.CREATED

    link.enabled = enabled
    db.session.commit()
    return ProjectSecretDTO.from_model(link).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/secrets/<label>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_secret(project_id: int, label: str):
    """
    PATCH /projects/<project_id>/secrets/<label> endpoint. Turns the link on or off (enabled),
    or revokes and re-grants it (revoked), which is admin only and takes effect at once.
    """
    link = _secret_link(project_id, label)
    body = request.json or {}
    fields = {"enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a secret")

    for field in body:
        setattr(link, field, body[field])
    db.session.commit()
    return ProjectSecretDTO.from_model(link).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/secrets/<label>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project_secret(project_id: int, label: str):
    """
    DELETE /projects/<project_id>/secrets/<label> endpoint. Unlinks the secret, not the secret
    itself: a soft delete that also revokes the link.
    """
    link = _secret_link(project_id, label)
    link.soft_delete()
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


def _results_link(project_id: int, repository_id: int) -> ProjectResultsRepository:
    return _link(ProjectResultsRepository, project_id, repository_id, f"Results repository {repository_id}")


def _check_results_loop(assignment: ProjectResultsRepository):
    """Refuses the change, rolling it back, if the results would land where a trigger watches."""
    try:
        check_no_loop(assignment.results_repository.provider_id, assignment.results_repository.repo_path)
    except InvalidRequest:
        db.session.rollback()
        raise


@bp.route('/<int:project_id>/repositories/results', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_project_results_repositories(project_id: int):
    """
    GET /projects/<project_id>/repositories/results endpoint. The project's results repository
    link, an inactive one included with its flags, so a project always lists exactly one.
    """
    Project.get_by_id(project_id)
    links = ProjectResultsRepository.query.filter_by(project_id=project_id).order_by(ProjectResultsRepository.id)
    return [ProjectResultsRepositoryDTO.from_model(a).dump() for a in links], HTTPStatus.OK


@bp.route('/<int:project_id>/repositories/results/<int:repository_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_project_results_repository(project_id: int, repository_id: int):
    """
    GET /projects/<project_id>/repositories/results/<repository_id> endpoint. The repository is the global one's id.
    """
    return ProjectResultsRepositoryDTO.from_model(_results_link(project_id, repository_id)).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/repositories/results/<int:repository_id>', methods=['PUT'])
@audit
@auth(scope='can_admin_dataset')
def put_project_results_repository(project_id: int, repository_id: int):
    """
    PUT /projects/<project_id>/repositories/results/<repository_id> endpoint. Links a global
    results repository to the project, which has one, 201, and replaces the project's settings
    if it is linked already, 200. Linking needs the project locked. Changing the settings of
    the link needs no lock: a change of target_dir is caught by the
    configuration snapshot of the tasks created before, which then fail instead of delivering there.
    Body: {"target_dir": "results", "owned_by_federated_node": true, "enabled": true}, the last
    two are optional.
    """
    project = Project.get_by_id(project_id)
    body = request.json or {}
    if not set(body) <= {"target_dir", "owned_by_federated_node", "enabled"} or not body.get("target_dir"):
        raise InvalidRequest("Provide target_dir and, optionally, owned_by_federated_node and enabled")
    for field in ("owned_by_federated_node", "enabled"):
        if not isinstance(body.get(field, True), bool):
            raise InvalidRequest(f"{field} must be a boolean")
    target_dir = normalise_dir(body["target_dir"])
    if not target_dir:
        raise InvalidRequest("target_dir is required")

    repo = ResultsRepository.get_by_id(repository_id)
    link = ProjectResultsRepository.query.filter_by(project_id=project.id).first()
    if link and link.results_repository_id != repo.id:
        raise InvalidRequest(f"Project {project.id} already has a results repository", HTTPStatus.CONFLICT)
    if link is None:
        require_locked(project)

    created = link is None
    if created:
        link = ProjectResultsRepository(project.id, repo.id, target_dir)
        link.add(commit=False)
    link.target_dir = target_dir
    link.owned_by_federated_node = body.get("owned_by_federated_node", True)
    link.enabled = body.get("enabled", True)
    db.session.flush()
    _check_results_loop(link)
    db.session.commit()
    return ProjectResultsRepositoryDTO.from_model(link).dump(), HTTPStatus.CREATED if created else HTTPStatus.OK


@bp.route('/<int:project_id>/repositories/results/<int:repository_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_results_repository(project_id: int, repository_id: int):
    """
    PATCH /projects/<project_id>/repositories/results/<repository_id> endpoint. Changes where
    the project's results go (target_dir, owned_by_federated_node), at any time (the tasks created
    before fail instead of delivering to the new place), or turns the link on or
    off (enabled), or revokes and re-grants it
    (revoked), which is admin only and takes effect at once.
    """
    link = _results_link(project_id, repository_id)
    body = request.json or {}
    fields = {"target_dir", "owned_by_federated_node", "enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body.keys() - {"target_dir"}:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a results repository")

    if "target_dir" in body:
        target_dir = normalise_dir(body["target_dir"] or "")
        if not target_dir:
            raise InvalidRequest("target_dir cannot be empty")
        body["target_dir"] = target_dir
    for field in body:
        setattr(link, field, body[field])
    db.session.flush()
    _check_results_loop(link)
    db.session.commit()
    return ProjectResultsRepositoryDTO.from_model(link).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/repositories/results/<int:repository_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project_results_repository(project_id: int, repository_id: int):
    """
    DELETE /projects/<project_id>/repositories/results/<repository_id> endpoint. Unlinks the
    repository, not the repository itself: a soft delete that also revokes the link. A task of the
    project still in flight gets a REVOKED result.
    """
    link = _results_link(project_id, repository_id)
    link.soft_delete()
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT
