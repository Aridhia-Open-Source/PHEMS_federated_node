"""
datasets-related endpoints. Datasets are global: a project reaches one through its
project resource, see projects_api (/projects/<id>/datasets). Creating, editing and deleting are
admin-only. Deleting a dataset is a soft delete, refused with a 409 naming the projects it is assigned to unless
?force=true:
- GET /global/datasets
- POST /global/datasets
- GET /global/datasets/id
- PATCH /global/datasets/id (200 like every other PATCH (?) assumed by the implementer, owner to confirm)
- DELETE /global/datasets/id
- GET /global/datasets/id/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends

from app.dtos.base import PageDTO, page_of
from app.dtos.dataset import DatasetDTO, DatasetPatchRequest, DatasetRequest
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.helpers.soft_delete import delete_global
from app.helpers.wrappers import Caller, get_caller, require_scope
from app.models.dataset import Dataset
from app.models.extras.catalogue import Catalogue
from app.models.extras.dictionary import Dictionary
from app.models.secret import Secret


router = APIRouter(prefix='/global/datasets', tags=["datasets"])
session = db.session


@router.get('/', response_model=PageDTO[DatasetDTO], dependencies=[Depends(require_scope('can_access_dataset'))])
@router.get('', response_model=PageDTO[DatasetDTO], dependencies=[Depends(require_scope('can_access_dataset'))])
def get_datasets(page: int = 1, per_page: int = 25):
    """
    GET /global/datasets/ endpoint. Returns a list of all datasets
    """
    return page_of(Dataset.get_all(page, per_page), DatasetDTO)


def _reject_project(body: dict):
    """A dataset belongs to no project, so naming one is a mistake, not something to ignore."""
    if "project_id" in body:
        raise InvalidRequest(
            "project_id is not accepted, datasets are global. Assign one with "
            "PUT /projects/<id>/datasets/<dataset id>"
        )


def _reject_credentials(body: dict):
    """Credentials live in a k8s secret, so sending them here is a mistake, not something to ignore."""
    if "username" in body or "password" in body:
        raise InvalidRequest(
            "username and password are not accepted. Create a secret with POST /global/secrets "
            "(values USERNAME and PASSWORD) and pass its label as secret_label"
        )


def _reject_taken_name(name: str, own_id: int | None = None):
    """Dataset names are unique. The name is already lowercased, as it is stored."""
    taken = Dataset.query.filter(Dataset.name == name)
    if own_id is not None:
        taken = taken.filter(Dataset.id != own_id)
    if taken.first():
        raise InvalidRequest(f"Dataset {name} already exists", HTTPStatus.CONFLICT)


@router.post('/', status_code=HTTPStatus.CREATED, response_model=DatasetDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
@router.post('', status_code=HTTPStatus.CREATED, response_model=DatasetDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
def post_datasets(body: dict = Body(default_factory=dict)):
    """
    POST /global/datasets/ endpoint. Creates a new global dataset. Admin only. A name
    already taken (case-insensitive) is a 409. A disabled secret_label is a 400
    """
    try:
        _reject_credentials(body)
        _reject_project(body)
        req = DatasetRequest.parse(body)
        _reject_taken_name(req.name)
        secret = Secret.get_enabled_by_label(req.secret_label)
        fields = req.model_dump(exclude={"secret_label", "catalogue", "dictionaries"})
        cata_body = req.catalogue
        dict_body = req.dictionaries
        dataset = Dataset(secret_id=secret.id, **fields)

        dataset.add(commit=False)
        if cata_body:
            cata_data = Catalogue.validate(cata_body)
            catalogue = Catalogue(dataset=dataset, **cata_data)
            catalogue.add(commit=False)

        for d in dict_body:
            dict_data = Dictionary.validate(d)
            dictionary = Dictionary(dataset=dataset, **dict_data)
            dictionary.add(commit=False)

        session.commit()

        return DatasetDTO.from_model(dataset)

    except Exception:
        session.rollback()
        raise


@router.get('/{dataset_id}', response_model=DatasetDTO, dependencies=[Depends(require_scope('can_access_dataset'))])
def get_dataset(dataset_id: int):
    """
    GET /global/datasets/id endpoint. Gets dataset with a give id
    """
    ds = Dataset.get_by_id(dataset_id)
    return DatasetDTO.from_model(ds)


@router.delete('/{dataset_id}', status_code=HTTPStatus.NO_CONTENT,
               dependencies=[Depends(require_scope('can_do_admin'))])
def delete_dataset(dataset_id: int, force: bool = False):
    """
    DELETE /global/datasets/id endpoint. Soft deletes the dataset. A 409 names the projects it is assigned to,
        unless ?force=true, which also revokes and deletes their project resources. Its k8s secret is left alone: it has its own lifecycle (/global/secrets) and
        other datasets may share it. Admin only.
    """
    ds = Dataset.get_by_id(dataset_id)
    delete_global(ds, ds.project_assignments, force)


@router.patch('/{dataset_id}', response_model=DatasetDTO, dependencies=[Depends(require_scope('can_do_admin'))])
def patch_dataset(dataset_id: int, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /global/datasets/id endpoint. Edits an existing dataset with a given id. The tasks created before
    are pinned to the old setup and fail instead of running against the new one. Admin only. Returns 200. A disabled secret_label is a 400, unless it is the
    one already in use. Enabling the dataset is a 409 while its secret (the new one, if secret_label is also sent) is disabled or deleted. `revoked` (a boolean) withdraws the dataset from every project at once, or restores it:
    the tasks that use it fail and nothing of theirs is delivered while it is revoked. It does not change `enabled`.
    """
    ds = Dataset.get_by_id(dataset_id)

    _reject_project(body)
    _reject_credentials(body)
    req = DatasetPatchRequest.parse(body)
    if not req.model_fields_set:
        raise InvalidRequest("No field to update")
    if req.revoked is not None and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")
    fields = req.model_dump(exclude_unset=True, exclude={"catalogue", "dictionaries", "secret_label"})
    cata_body = req.catalogue
    dict_body = req.dictionaries or []
    if req.name is not None:
        _reject_taken_name(req.name, ds.id)
    secret = ds.secret
    if req.secret_label is not None:
        secret = Secret.get_enabled_by_label(req.secret_label, ds.secret_id)
        fields["secret_id"] = secret.id
    if req.enabled:
        secret.require_usable()

    try:
        ds.update(**fields)
        # TODO(DAR): the DAR Keycloak clients are no longer patched on rename, disconnected
        # for now.
        # Update catalogue and dictionaries
        if cata_body:
            Catalogue.update_or_create(cata_body, ds)

        for d in dict_body:
            Dictionary.update_or_create(d, ds)
    except Exception:
        session.rollback()
        raise

    session.commit()
    return DatasetDTO.from_model(ds)
