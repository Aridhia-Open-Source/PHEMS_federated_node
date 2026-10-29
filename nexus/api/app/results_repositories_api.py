"""
results repository endpoints, global: a project is assigned one under
/projects/<id>/repositories/results (see projects_api.py). Create, edit and delete are admin
only. Deleting one is a soft delete, refused with a 409 naming the projects it is assigned to unless ?force=true. A secret_label naming a disabled secret is a 400 on POST and PATCH.
- GET /global/repositories/results
- GET /global/repositories/results/<id>
- POST /global/repositories/results
- PATCH /global/repositories/results/<id>
- DELETE /global/repositories/results/<id>
- GET /global/repositories/results/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from fastapi import APIRouter, Depends

from app.dtos.repository_uri import RepositoryPatchRequest, RepositoryRequest
from app.dtos.results_repository import ResultsRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.helpers.soft_delete import delete_global
from app.helpers.wrappers import Caller, get_caller, require_scope
from app.models.git_provider import GitProvider
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret

router = APIRouter(
    prefix='/global/repositories/results', tags=["results_repositories"],
    dependencies=[Depends(require_scope('can_admin_dataset'))]
)
session = db.session


@router.get('/', response_model=list[ResultsRepositoryDTO])
@router.get('', response_model=list[ResultsRepositoryDTO])
def get_repositories():
    """
    GET /global/repositories/results/ — list the repositories
    """
    return [ResultsRepositoryDTO.from_model(r) for r in ResultsRepository.query.order_by(ResultsRepository.id)]


@router.get('/{repo_id}', response_model=ResultsRepositoryDTO)
def get_repository(repo_id: int):
    """
    GET /global/repositories/results/<id> — get a single repository
    """
    repo = ResultsRepository.get_by_id(repo_id)
    return ResultsRepositoryDTO.from_model(repo)


@router.delete('/{repo_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(require_scope('can_do_admin'))])
def delete_repository(repo_id: int, force: bool = False):
    """
    DELETE /global/repositories/%s/<id> — soft delete the repository. A 409 names the projects it is assigned to, unless ?force=true, which also revokes and deletes their project resources.
    """
    repo = ResultsRepository.get_by_id(repo_id)
    delete_global(repo, repo.project_assignments, force)


@router.post('/', status_code=HTTPStatus.CREATED, response_model=ResultsRepositoryDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
@router.post('', status_code=HTTPStatus.CREATED, response_model=ResultsRepositoryDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
def post_repository(req: RepositoryRequest):
    """
    POST /global/repositories/results/ — create a new repository, assigned to no project yet. project_id
    and target_dir are not accepted, results repositories are global: assign one with
    PUT /projects/<id>/repositories/results/<repository id>
    """
    provider = GitProvider.get_by_request_id(req.provider_id)
    secret = Secret.get_enabled_by_label(req.secret_label)

    try:
        repo = ResultsRepository(
            provider_id=provider.id,
            repo_path=req.repo_path,
            secret_id=secret.id,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if ResultsRepository.query.filter_by(provider_id=provider.id, repo_path=repo.repo_path).first():
        raise InvalidRequest(
            f"Results repository {provider.uri}/{repo.repo_path} already exists", code=HTTPStatus.CONFLICT
        )
    repo.add()

    return ResultsRepositoryDTO.from_model(repo)


@router.patch('/{repo_id}', response_model=ResultsRepositoryDTO, dependencies=[Depends(require_scope('can_do_admin'))])
def patch_repository(repo_id: int, req: RepositoryPatchRequest, caller: Caller = Depends(get_caller)):
    """
    PATCH /global/repositories/results/<id> — update repository. The tasks created
    before are pinned to the old setup and fail instead of running against the new one. A disabled secret cannot be
    named (400), unless it is the one already in use. Enabling the repository is a 409 while its secret (the new one,
    if secret_label is also sent) is disabled or deleted. `revoked` (a boolean) withdraws the repository from every
    project at once, or restores it, and does not change `enabled`: see helpers/task_config.revoked_resources.
    """
    repo = ResultsRepository.get_by_id(repo_id)

    sent = req.model_fields_set
    if not sent:
        raise InvalidRequest("No fields provided to update")
    if 'revoked' in sent and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a results repository")

    secret = repo.secret
    if 'secret_label' in sent:
        secret = Secret.get_enabled_by_label(req.secret_label, repo.secret_id)
    if 'enabled' in sent and req.enabled:
        secret.require_usable()
    repo.secret_id = secret.id

    if 'enabled' in sent:
        repo.enabled = req.enabled

    if 'revoked' in sent:
        repo.revoked = req.revoked

    if 'provider_id' in sent:
        provider = GitProvider.get_by_request_id(req.provider_id)
        if ResultsRepository.query.filter(
            ResultsRepository.provider_id == provider.id, ResultsRepository.repo_path == repo.repo_path, ResultsRepository.id != repo.id
        ).first():
            raise InvalidRequest(
                f"Results repository {provider.uri}/{repo.repo_path} already exists", code=HTTPStatus.CONFLICT
            )
        repo.provider_id = provider.id

    session.commit()
    return ResultsRepositoryDTO.from_model(repo)
