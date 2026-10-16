"""
datasets-related endpoints. Datasets are global: a project reaches one through its
link, see projects_api (/projects/<id>/datasets). Creating, editing and deleting are
admin-only, and editing or deleting needs every project the dataset is linked to locked
and drained:
- GET /global/datasets
- POST /global/datasets
- GET /global/datasets/id
- PATCH /global/datasets/id (200 like every other PATCH (?) assumed by the implementer, owner to confirm)
- DELETE /global/datasets/id
- GET /global/datasets/id/healthcheck, see healthcheck_api.py
"""
import logging
from http import HTTPStatus

from flask import Blueprint, request

from .dtos.base import page_of
from .dtos.dataset import DatasetDTO, DatasetPatchRequest, DatasetRequest
from .helpers.base_model import db
from .helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from .helpers.project_lock import require_all_drained
from .helpers.query_validator import validate
from .helpers.wrappers import audit, auth
from .models.dataset import Dataset
from .models.extras.catalogue import Catalogue
from .models.secret import Secret
from .models.extras.dictionary import Dictionary


bp = Blueprint('datasets', __name__, url_prefix='/global/datasets')
session = db.session

logger = logging.getLogger("dataset_api")
logger.setLevel(logging.INFO)


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets():
    """
    GET /global/datasets/ endpoint. Returns a list of all datasets
    """
    return page_of(Dataset.get_all(), DatasetDTO), HTTPStatus.OK


def _reject_project(body: dict | None):
    """A dataset belongs to no project, so naming one is a mistake, not something to ignore."""
    if isinstance(body, dict) and "project_id" in body:
        raise InvalidRequest(
            "project_id is not accepted, datasets are global. Link one with "
            "PUT /projects/<id>/datasets/<dataset id>"
        )


def _reject_credentials(body: dict | None):
    """Credentials live in a k8s secret, so sending them here is a mistake, not something to ignore."""
    if isinstance(body, dict) and ("username" in body or "password" in body):
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


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_do_admin')
def post_datasets():
    """
    POST /global/datasets/ endpoint. Creates a new global dataset. Admin only. A name
    already taken (case-insensitive) is a 409. A disabled secret_label is a 400
    """
    try:
        _reject_credentials(request.json)
        _reject_project(request.json)
        req = DatasetRequest.parse(request.json)
        _reject_taken_name(req.name)
        secret = Secret.get_enabled_by_label(req.secret_label)
        body = req.model_dump(exclude={"secret_label", "catalogue", "dictionaries"})
        cata_body = req.catalogue
        dict_body = req.dictionaries
        dataset = Dataset(secret_id=secret.id, **body)

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

        return DatasetDTO.from_model(dataset).dump(), 201

    except Exception:
        session.rollback()
        raise


# @audit
@bp.route('/<int:dataset_id>', methods=['GET'])
@auth(scope='can_access_dataset')
@audit
def get_dataset(dataset_id: int):
    """
    GET /global/datasets/id endpoint. Gets dataset with a give id
    """
    ds = Dataset.get_by_id(dataset_id)
    return DatasetDTO.from_model(ds).dump(), HTTPStatus.OK


@bp.route('/<int:dataset_id>', methods=['DELETE'])
@audit
@auth(scope='can_do_admin')
def delete_dataset(dataset_id: int):
    """
    DELETE /global/datasets/id endpoint. Deletes the dataset and its links, once every
        project it is linked to is locked and drained. Refused while a task ran on it. Its
        k8s secret is left alone: it has its own lifecycle (/global/secrets) and other datasets
        may share it. Admin only.
    """
    logger.error(f"deleting ({dataset_id})")
    ds = Dataset.get_by_id(dataset_id)
    assignments = list(ds.project_assignments)
    require_all_drained([a.project for a in assignments])
    try:
        for assignment in assignments:
            assignment.delete(False)
        ds.delete()
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc
    return {}, 204


@bp.route('/<int:dataset_id>', methods=['PATCH'])
# @audit
@auth(scope='can_do_admin')
def patch_dataset(dataset_id: int):
    """
    PATCH /global/datasets/id endpoint. Edits an existing dataset with a given id, once every
    project it is linked to is locked and drained. Admin only. Returns 200. A disabled secret_label is a 400, unless it is the
    one already in use.
    """
    ds = Dataset.get_by_id(dataset_id)

    body = request.json
    _reject_project(body)
    _reject_credentials(body)
    req = DatasetPatchRequest.parse(body)
    if not req.model_fields_set:
        raise InvalidRequest("No field to update")
    require_all_drained([a.project for a in ds.project_assignments])
    body = req.model_dump(exclude_unset=True, exclude={"catalogue", "dictionaries", "secret_label"})
    cata_body = req.catalogue
    dict_body = req.dictionaries or []
    if req.name is not None:
        _reject_taken_name(req.name, ds.id)
    if req.secret_label is not None:
        body["secret_id"] = Secret.get_enabled_by_label(req.secret_label, ds.secret_id).id

    try:
        ds.update(**body)
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
    return DatasetDTO.from_model(ds).dump(), HTTPStatus.OK

