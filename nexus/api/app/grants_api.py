"""
Grants on projects and global records (ADR 0037). Each record path gets:
- GET <record path>/grants: lists the record's grants
- POST <record path>/grants: adds one (409 on a duplicate)
- DELETE <record path>/grants/{grant_id}: removes one
- PUT <record path>/owner: SuperUser only; sets owned_by to the caller (no body) or to a named user, and gives
  them manage. The former owner's manage grant stays.
Only a manage holder or SuperUser changes a record's grants; a deny is a 409 naming the owner. Checked through
Cedar (Access(model=..., action=Action.MANAGE)); claiming and re-assigning stay a SuperUser role check on top.
Listing them is a read, checked with the other reads.
"""
from collections.abc import Callable
from http import HTTPStatus

from fastapi import APIRouter, Depends

from app.dtos.grant import GrantDTO, GrantRequest, OwnerRequest
from app.rules.authz import Access, Action
from app.database.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.rules.ownership import add_manage
from app.dtos.caller import Caller
from app.helpers.wrappers import get_caller
from app.models.dataset import Dataset
from app.models.git_provider import GitProvider
from app.models.grant import MANAGE, USER, Grant
from app.models.node_role import NodeRole
from app.models.project import Project
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret
from app.models.trigger_repository import TriggerRepository
from app.models.user import OwnedMixin, User


def _grants_router(prefix: str, tag: str, load: Callable, model: type[OwnedMixin]) -> APIRouter:
    """
    The grant routes of one record path. load is the dependency that gets the record from the path, 404 if
    missing; its parameter names the path parameter. The writes get the record from Access instead.
    """
    router = APIRouter(prefix=prefix, tags=[tag])
    manage = Access(model=model, action=Action.MANAGE)

    @router.get('/grants', response_model=list[GrantDTO])
    def get_grants(record: OwnedMixin = Depends(load)):
        """The record's grants, oldest first."""
        return [GrantDTO.from_model(grant) for grant in db.session.scalars(Grant.of(record).order_by(Grant.id))]

    @router.post('/grants', status_code=HTTPStatus.CREATED, response_model=GrantDTO)
    def post_grant(req: GrantRequest, record: OwnedMixin = Depends(manage), caller: Caller = Depends(get_caller)):
        """Adds a grant. Body: {"relation": "read", "subject_type": "group", "subject_id": "/studies/uc1",
        "expires_at": "2027-01-01T00:00:00Z"}; expires_at is optional."""
        duplicate = db.session.scalars(Grant.of(record).where(
            Grant.relation == req.relation, Grant.subject_type == req.subject_type, Grant.subject_id == req.subject_id,
        )).first()
        if duplicate is not None:
            raise InvalidRequest(f"{duplicate!r} already exists", HTTPStatus.CONFLICT)
        grant = Grant(
            object_type=record.authz_type, object_id=record.id, created_by_id=caller.user.id, **req.model_dump(),
        )
        grant.add()
        return GrantDTO.from_model(grant)

    @router.delete('/grants/{grant_id}', status_code=HTTPStatus.NO_CONTENT)
    def delete_grant(grant_id: int, record: OwnedMixin = Depends(manage)):
        """Removes a grant. The grant that gives the owned_by user manage stays while they own the record (409)."""
        grant = db.session.scalars(Grant.of(record).where(Grant.id == grant_id)).first()
        if grant is None:
            raise DBRecordNotFoundError(f"Grant {grant_id} does not exist on {record!r}")
        if (grant.relation, grant.subject_type, grant.subject_id) == (MANAGE, USER, record.owned_by_id):
            raise InvalidRequest(
                f"{grant!r} is the owner's: change the owner first", HTTPStatus.CONFLICT
            )
        grant.delete()

    @router.put('/owner', response_model=list[GrantDTO])
    def put_owner(
        req: OwnerRequest | None = None, record: OwnedMixin = Depends(manage), caller: Caller = Depends(get_caller),
    ):
        """
        SuperUser only (409 for anyone else): claims the record (no body), or re-assigns it to a user that has
        called nexus-api ({"user_id": "..."}, 404 if unknown). Returns the record's grants.
        """
        if caller.role != NodeRole.SUPERUSER:
            raise InvalidRequest("Only the SuperUser can claim or re-assign a record", HTTPStatus.CONFLICT)
        user_id = req.user_id if req and req.user_id else caller.user.id
        if db.session.get(User, user_id) is None:
            raise DBRecordNotFoundError(f"User {user_id} does not exist")
        record.owned_by_id = user_id
        add_manage(record, USER, user_id, caller)
        db.session.commit()
        return get_grants(record)

    return router


def _load_project(project_id: int) -> Project:
    return Project.get_by_id(project_id)


def _load_dataset(dataset_id: int) -> Dataset:
    return Dataset.get_by_id(dataset_id)


def _load_provider(provider_id: int) -> GitProvider:
    return GitProvider.get_by_id(provider_id)


def _load_secret(label: str) -> Secret:
    secret = Secret.query.filter(Secret.label == label).one_or_none()
    if secret is None:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")
    return secret


def _load_trigger_repository(repo_id: int) -> TriggerRepository:
    return TriggerRepository.get_by_id(repo_id)


def _load_results_repository(repo_id: int) -> ResultsRepository:
    return ResultsRepository.get_by_id(repo_id)


routers = (
    _grants_router('/projects/{project_id}', 'projects', _load_project, Project),
    _grants_router('/global/datasets/{dataset_id}', 'datasets', _load_dataset, Dataset),
    _grants_router('/global/providers/{provider_id}', 'git_providers', _load_provider, GitProvider),
    _grants_router('/global/secrets/{label}', 'secrets', _load_secret, Secret),
    _grants_router(
        '/global/repositories/triggers/{repo_id}', 'trigger_repositories', _load_trigger_repository, TriggerRepository,
    ),
    _grants_router(
        '/global/repositories/results/{repo_id}', 'results_repositories', _load_results_repository, ResultsRepository,
    ),
)
