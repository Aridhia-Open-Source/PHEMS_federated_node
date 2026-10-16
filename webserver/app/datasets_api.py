"""
datasets-related endpoints. Datasets are global: a project reaches one through its
link, see projects_api (/projects/<id>/datasets). Creating, editing and deleting are
admin-only, and editing or deleting needs every project the dataset is linked to locked
and drained:
- GET /global/datasets
- POST /global/datasets
- GET /global/datasets/id
- PATCH /global/datasets/id
- DELETE /global/datasets/id
- GET /global/datasets/id/healthcheck, see healthcheck_api.py
"""
import logging
from http import HTTPStatus

from flask import Blueprint, request

from .dtos.base import page_of
from .dtos.dataset import DatasetDTO
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
    if body and "project_id" in body:
        raise InvalidRequest(
            "project_id is not accepted, datasets are global. Link one with "
            "PUT /projects/<id>/datasets/<dataset id>"
        )


def _reject_credentials(body: dict | None):
    """Credentials live in a k8s secret, so sending them here is a mistake, not something to ignore."""
    if body and ("username" in body or "password" in body):
        raise InvalidRequest(
            "username and password are not accepted. Create a secret with POST /global/secrets "
            "(values USERNAME and PASSWORD) and pass its label as secret_label"
        )


def _resolve_secret(body: dict) -> dict:
    """Swaps the secret_label a request carries for the secret's id."""
    if not body.get("secret_label"):
        raise InvalidRequest("secret_label is required")
    body["secret_id"] = Secret.get_by_label(body.pop("secret_label")).id
    return body


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_do_admin')
def post_datasets():
    """
    POST /global/datasets/ endpoint. Creates a new global dataset. Admin only
    """
    try:
        _reject_credentials(request.json)
        _reject_project(request.json)
        body = Dataset.validate(_resolve_secret(dict(request.json)))
        if not isinstance(body.get("enabled", True), bool):
            raise InvalidRequest("enabled must be a boolean")
        cata_body = body.pop("catalogue", {})
        dict_body = body.pop("dictionaries", [])
        dataset = Dataset(**body)

        dataset.add(commit=False)
        if cata_body:
            cata_data = Catalogue.validate(cata_body)
            catalogue = Catalogue(dataset=dataset, **cata_data)
            catalogue.add(commit=False)

        # Dictionary should be a list of dict. If not raise an error and revert changes
        if not isinstance(dict_body, list):
            session.rollback()
            raise InvalidRequest("dictionaries should be a list.")

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
    project it is linked to is locked and drained. Admin only.
    """
    ds = Dataset.get_by_id(dataset_id)

    # Update validation doesn't have required fields
    body = request.json
    _reject_project(body)
    require_all_drained([a.project for a in ds.project_assignments])
    body.pop("id", None)
    cata_body = body.pop("catalogue", {})
    dict_body = body.pop("dictionaries", [])

    # Dictionary should be a list of dict. If not raise an error and revert changes
    if not isinstance(dict_body, list):
        session.rollback()
        raise InvalidRequest("dictionaries should be a list.")

    # port is non-nullable, so an explicit null would hit the DB constraint
    if "port" in body and (not isinstance(body["port"], int) or isinstance(body["port"], bool)):
        raise InvalidRequest("port must be an integer")

    if "enabled" in body and not isinstance(body["enabled"], bool):
        raise InvalidRequest("enabled must be a boolean")

    if "secret_label" in body:
        _resolve_secret(body)

    for k in body:
        if not hasattr(ds, k):
            raise InvalidRequest(f"Field {k} is not a valid one")

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
    return DatasetDTO.from_model(ds).dump(), HTTPStatus.ACCEPTED

