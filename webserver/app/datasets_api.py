"""
datasets-related endpoints:
- GET /datasets
- POST /datasets
- GET /datasets/id
- DELETE /datasets/id
- GET /datasets/id/catalogues
- GET /datasets/id/dictionaries
- GET /datasets/id/dictionaries/table_name
- POST /datasets/token_transfer
- POST /datasets/selection/beacon
"""
from datetime import datetime
from flask import Blueprint, request
from kubernetes.client import ApiException
import logging

from .helpers.base_model import db
from .helpers.const import DEFAULT_NAMESPACE
from .helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from .helpers.keycloak import Keycloak
from .helpers.kubernetes import KubernetesClient
from .helpers.query_validator import validate
from .helpers.wrappers import auth, audit
from .models.dataset import Dataset
from .models.catalogue import Catalogue
from .models.dictionary import Dictionary
from .models.request import Request


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
    return Dataset.get_all(), 200

@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def post_datasets():
    """
    POST /datasets/ endpoint. Creates a new dataset
    """
    try:
        body = Dataset.validate(request.json)
        cata_body = body.pop("catalogue", {})
        dict_body = body.pop("dictionaries", [])
        dataset = Dataset(**body)

        kc_client = Keycloak()
        token_info = kc_client.decode_token(kc_client.get_token_from_headers())
        dataset.add(
            commit=False,
            user_id=token_info['sub']
        )
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
        return { "dataset_id": dataset.id, "url": dataset.url }, 201

    except:
        session.rollback()
        raise

@bp.route('/<int:dataset_id>', methods=['GET'])
@bp.route('/<dataset_name>', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_by_id_or_name(dataset_id:int=None, dataset_name:str=None):
    """
    GET /datasets/id endpoint. Gets dataset with a give id
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
    return Dataset.sanitized_dict(ds), 200

@bp.route('/<int:dataset_id>', methods=['DELETE'])
@bp.route('/<dataset_name>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_datasets_by_id_or_name(dataset_id:int=None, dataset_name:str=None):
    """
    DELETE /datasets/id endpoint. Deletes the dataset from the db and k8s secrets
        the DB entry deletion is prioritized to the k8s secret.
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
    secret_name = ds.get_creds_secret_name()

    try:
        ds.delete(False)
    except:
        session.rollback()
        raise InvalidRequest("Error while deleting the record")

    v1 = KubernetesClient()
    try:
        v1.delete_namespaced_secret(secret_name, DEFAULT_NAMESPACE)
    except ApiException as apie:
        if apie.status != 404:
            logger.error(apie)
            session.rollback()
            raise InvalidRequest("Could not clear the secrets properly") from apie

    session.commit()
    return {}, 204

@bp.route('/<int:dataset_id>', methods=['PATCH'])
@bp.route('/<dataset_name>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_datasets_by_id_or_name(dataset_id:int=None, dataset_name:str=None):
    """
    PATCH /datasets/id endpoint. Edits an existing dataset with a given id
    """
    ds = Dataset.get_dataset_by_name_or_id(dataset_id, dataset_name)

    old_ds_name = ds.name
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
        if not hasattr(ds, k) and k not in ["username", "password"]:
            raise InvalidRequest(f"Field {k} is not a valid one")

    try:
        ds.update(**body)
        # Also make sure all the request clients are updated with this
        if body.get("name", None) is not None and body.get("name", None) != old_ds_name:
            dars = Request.query.with_entities(Request.requested_by, Request.project_name)\
                .filter(Request.dataset_id == ds.id, Request.proj_end > datetime.now())\
                .group_by(Request.requested_by, Request.project_name).all()
            for dar in dars:
                update_args = {
                    "name": f"{ds.id}-{ds.name}",
                    "displayName": f"{ds.id} - {ds.name}"
                }

                user = Keycloak().get_user_by_id(dar[0])
                req_by = user["email"]
                kc_client = Keycloak(client=f"Request {req_by} - {dar[1]}")
                kc_client.patch_resource(f"{ds.id}-{old_ds_name}", **update_args)
        # Update catalogue and dictionaries
        if cata_body:
            Catalogue.update_or_create(cata_body, ds)

        for d in dict_body:
            Dictionary.update_or_create(d, ds)
    except:
        session.rollback()
        raise

    session.commit()
    return Dataset.sanitized_dict(ds), 204

@bp.route('/<dataset_name>/catalogue', methods=['GET'])
@bp.route('/<int:dataset_id>/catalogue', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_catalogue_by_id_or_name(dataset_id=None, dataset_name=None):
    """
    GET /datasets/dataset_name/catalogue endpoint. Gets dataset's catalogue
    GET /datasets/id/catalogue endpoint. Gets dataset's catalogue
    """
    dataset = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)

    cata = Catalogue.query.filter(Catalogue.dataset_id == dataset.id).one_or_none()
    if not cata:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no catalogue.")
    return cata.sanitized_dict(), 200

@bp.route('/<dataset_name>/dictionaries', methods=['GET'])
@bp.route('/<int:dataset_id>/dictionaries', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_dictionaries_by_id_or_name(dataset_id=None, dataset_name=None):
    """
    GET /datasets/dataset_name/dictionaries endpoint.
    GET /datasets/id/dictionaries endpoint.
        Gets the dataset's list of dictionaries
    """
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id, name=dataset_name)

    dictionary = Dictionary.query.filter(Dictionary.dataset_id == dataset.id).all()
    if not dictionary:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no dictionaries.")

    return [dc.sanitized_dict() for dc in dictionary], 200


@bp.route('/<dataset_name>/dictionaries/<table_name>', methods=['GET'])
@bp.route('/<int:dataset_id>/dictionaries/<table_name>', methods=['GET'])
@audit
@auth(scope='can_access_dataset')

def get_datasets_dictionaries_table_by_id_or_name(table_name, dataset_id=None, dataset_name=None):
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

    return [dc.sanitized_dict() for dc in dictionary], 200

@bp.route('/token_transfer', methods=['POST'])
@audit
@auth(scope='can_transfer_token', check_dataset=False)
def post_transfer_token():
    """
    POST /datasets/token_transfer endpoint.
        Returns a user's token based on an approved DAR
    """
    try:
        # Not sure we need all of this in the Request table...
        body = request.json
        if 'email' not in body["requested_by"].keys():
            raise InvalidRequest("Missing email from requested_by field")

        user = Keycloak().get_user_by_email(body["requested_by"]["email"])
        if not user:
            user = Keycloak().create_user(**body["requested_by"])

        body["requested_by"] = user["id"]
        ds_id = body.pop("dataset_id")
        body["dataset"] = Dataset.query.filter(Dataset.id == ds_id).one_or_none()
        if body["dataset"] is None:
            raise DBRecordNotFoundError(f"Dataset {ds_id} not found")

        req_attributes = Request.validate(body)
        req = Request(**req_attributes)
        req.add()
        return req.approve(), 201

    except KeyError as kexc:
        session.rollback()
        raise InvalidRequest(
            "Missing field. Make sure \"catalogue\" and \"dictionary\" entries are there"
        ) from kexc
    except:
        session.rollback()
        raise

@bp.route('/selection/beacon', methods=['POST'])
@audit
@auth(scope='can_access_dataset', check_dataset=False)
def select_beacon():
    """
    POST /dataset/datasets/selection/beacon endpoint.
        Checks the validity of a query on a dataset
    """
    body = request.json.copy()
    dataset = Dataset.query.filter(Dataset.id == body['dataset_id']).one_or_none()
    if dataset is None:
        raise DBRecordNotFoundError(f"Dataset with id {body['dataset_id']} does not exist")

    if validate(body['query'], dataset):
        return {
            "query": body['query'],
            "result": "Ok"
        }, 200
    return {
        "query": body['query'],
        "result": "Invalid"
    }, 500
