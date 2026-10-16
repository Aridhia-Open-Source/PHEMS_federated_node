"""
datasets-related endpoints. Datasets are global: a project reaches one through its
assignment, see projects_api (/projects/<id>/datasets). Creating, editing and deleting are
admin-only, and editing or deleting needs every project the dataset is assigned to locked
and drained:
- GET /datasets
- POST /datasets
- GET /datasets/id
- DELETE /datasets/id
- GET /datasets/id/catalogues
- GET /datasets/id/dictionaries
- GET /datasets/id/dictionaries/table_name
"""
import logging
from http import HTTPStatus

from flask import Blueprint, request

from .dtos.base import page_of
from .dtos.dataset import CatalogueDTO, DatasetDTO, DictionaryDTO
from .helpers.base_model import db
from .helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from .helpers.project_lock import require_all_drained
from .helpers.query_validator import validate
from .helpers.wrappers import audit, auth
from .models.dataset import Dataset
from .models.extras.catalogue import Catalogue
from .models.secret import Secret
from .models.extras.dictionary import Dictionary


bp = Blueprint('datasets', __name__, url_prefix='/datasets')
session = db.session

logger = logging.getLogger("dataset_api")
logger.setLevel(logging.INFO)


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets():
    """
    GET /datasets/ endpoint. Returns a list of all datasets
    """
    return page_of(Dataset.get_all(), DatasetDTO), HTTPStatus.OK


def _reject_project(body: dict | None):
    """A dataset belongs to no project, so naming one is a mistake, not something to ignore."""
    if body and "project_id" in body:
        raise InvalidRequest(
            "project_id is not accepted, datasets are global. Assign one with "
            "POST /projects/<id>/datasets"
        )


def _reject_credentials(body: dict | None):
    """Credentials live in a k8s secret, so sending them here is a mistake, not something to ignore."""
    if body and ("username" in body or "password" in body):
        raise InvalidRequest(
            "username and password are not accepted. Create a secret with POST /secrets "
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
@auth(scope='can_do_admin', check_dataset=False)
def post_datasets():
    """
    POST /datasets/ endpoint. Creates a new global dataset. Admin only
    """
    try:
        _reject_credentials(request.json)
        _reject_project(request.json)
        body = Dataset.validate(_resolve_secret(dict(request.json)))
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
@bp.route('/<dataset_name>', methods=['GET'])
@auth(scope='can_access_dataset')
@audit
def get_datasets_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    GET /datasets/id endpoint. Gets dataset with a give id
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
    return DatasetDTO.from_model(ds).dump(), HTTPStatus.OK


@bp.route('/<int:dataset_id>', methods=['DELETE'])
@bp.route('/<dataset_name>', methods=['DELETE'])
@audit
@auth(scope='can_do_admin', check_dataset=False)
def delete_datasets_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    DELETE /datasets/id endpoint. Deletes the dataset and its assignments, once every
        project it is assigned to is locked and drained. Refused while a task ran on it. Its
        k8s secret is left alone: it has its own lifecycle (/secrets) and other datasets
        may share it. Admin only.
    """
    logger.error(f"deleting ({dataset_id or dataset_name})")
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
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
@bp.route('/<dataset_name>', methods=['PATCH'])
# @audit
@auth(scope='can_do_admin', check_dataset=False)
def patch_datasets_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    PATCH /datasets/id endpoint. Edits an existing dataset with a given id, once every
    project it is assigned to is locked and drained. Admin only.
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)

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


@bp.route('/<dataset_name>/catalogue', methods=['GET'])
@bp.route('/<int:dataset_id>/catalogue', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_catalogue_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    GET /datasets/dataset_name/catalogue endpoint. Gets dataset's catalogue
    GET /datasets/id/catalogue endpoint. Gets dataset's catalogue
    """
    dataset = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)

    cata = Catalogue.query.filter(Catalogue.dataset_id == dataset.id).one_or_none()
    if not cata:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no catalogue.")
    return CatalogueDTO.from_model(cata).dump(), HTTPStatus.OK


@bp.route('/<dataset_name>/dictionaries', methods=['GET'])
@bp.route('/<int:dataset_id>/dictionaries', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_dictionaries_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    GET /datasets/dataset_name/dictionaries endpoint.
    GET /datasets/id/dictionaries endpoint.
        Gets the dataset's list of dictionaries
    """
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id, name=dataset_name)

    dictionary = Dictionary.query.filter(Dictionary.dataset_id == dataset.id).all()
    if not dictionary:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no dictionaries.")

    return [DictionaryDTO.from_model(dc).dump() for dc in dictionary], HTTPStatus.OK


@bp.route('/<dataset_name>/dictionaries/<table_name>', methods=['GET'])
@bp.route('/<int:dataset_id>/dictionaries/<table_name>', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_dictionaries_table_by_id_or_name(
    table_name: str,
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    GET /datasets/dataset_name/dictionaries/table_name endpoint.
    GET /datasets/id/dictionaries/table_name endpoint.
        Gets the dataset's table within its dictionaries
    """
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id, name=dataset_name)

    dictionary = Dictionary.query.filter(
        Dictionary.dataset_id == dataset.id,
        Dictionary.table_name == table_name
    ).all()
    if not dictionary:
        raise DBRecordNotFoundError(
            f"Dataset {dataset.name} has no dictionaries with table {table_name}."
        )

    return [DictionaryDTO.from_model(dc).dump() for dc in dictionary], HTTPStatus.OK
