"""
datasets-related endpoints:
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


def _reject_credentials(body: dict | None):
    """Credentials live in a k8s secret, so sending them here is a mistake, not something to ignore."""
    if body and ("username" in body or "password" in body):
        raise InvalidRequest(
            "username and password are not accepted. Create a secret with POST /secrets "
            "(values USERNAME and PASSWORD) and pass its label as secret_label"
        )


def _resolve_secret(body: dict, project_id: int) -> dict:
    """Swaps the project-local secret_label a request carries for the secret's id."""
    if not body.get("secret_label"):
        raise InvalidRequest("secret_label is required")
    body["secret_id"] = Secret.get_in_project(project_id, body.pop("secret_label")).id
    return body


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def post_datasets():
    """
    POST /datasets/ endpoint. Creates a new dataset
    """
    try:
        _reject_credentials(request.json)
        if not request.json.get("project_id"):
            raise InvalidRequest("project_id is required")
        body = Dataset.validate(_resolve_secret(dict(request.json), request.json["project_id"]))
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
@auth(scope='can_admin_dataset')
def delete_datasets_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    DELETE /datasets/id endpoint. Deletes the dataset. Its k8s secret is left alone: it
        has its own lifecycle (/secrets) and other datasets may share it.
    """
    logger.error(f"deleting ({dataset_id or dataset_name})")
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
    try:
        ds.delete()
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc
    return {}, 204


@bp.route('/<int:dataset_id>', methods=['PATCH'])
@bp.route('/<dataset_name>', methods=['PATCH'])
# @audit
@auth(scope='can_admin_dataset')
def patch_datasets_by_id_or_name(
    dataset_id: int | None = None,
    dataset_name: str | None = None
):
    """
    PATCH /datasets/id endpoint. Edits an existing dataset with a given id
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)

    # Update validation doesn't have required fields
    body = request.json
    body.pop("id", None)
    cata_body = body.pop("catalogue", {})
    dict_body = body.pop("dictionaries", [])

    # Dictionary should be a list of dict. If not raise an error and revert changes
    if not isinstance(dict_body, list):
        session.rollback()
        raise InvalidRequest("dictionaries should be a list.")

    for k in body:
        if not hasattr(ds, k):
            raise InvalidRequest(f"Field {k} is not a valid one")

    if "secret_label" in body:
        _resolve_secret(body, body.get("project_id", ds.project_id))

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
