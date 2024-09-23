"""
datasets-related endpoints:
- GET /datasets
- POST /datasets
- GET /datasets/id
- GET /datasets/id/catalogues
- GET /datasets/id/dictionaries
- GET /datasets/id/dictionaries/table_name
- POST /datasets/token_transfer
- POST /datasets/workspace/token
- POST /datasets/selection/beacon
"""
import json
from flask import Blueprint, request
from sqlalchemy import select

from .helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from .helpers.db import db
from .helpers.keycloak import Keycloak
from .helpers.query_validator import validate
from .helpers.wrappers import auth, audit
from .models.dataset import Dataset
from .models.catalogue import Catalogue
from .models.dictionary import Dictionary
from .models.request import Request


bp = Blueprint('datasets', __name__, url_prefix='/datasets')
session = db.session

def get_dataset_by_name(dataset_name):
    """
    Common funcion to get a dataset by name
    """
    dataset = Dataset.query.filter(Dataset.name.ilike(dataset_name)).first()
    if not dataset:
        raise DBRecordNotFoundError(f"Dataset {dataset_name} does not exist")
    return dataset

@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets():
    """
    GET /datasets/ endpoint. Returns a list of all datasets
    """
    return {
        "datasets": Dataset.get_all()
    }, 200

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
        dataset.add(commit=False, user_id=token_info['sub'])
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
@audit
@auth(scope='can_access_dataset')
def get_datasets_by_id(dataset_id):
    """
    GET /datasets/id endpoint. Gets dataset with a give id
    """
    ds = Dataset.query.filter(Dataset.id == dataset_id).one_or_none()
    if ds is None:
        raise DBRecordNotFoundError(f"Dataset with id {dataset_id} does not exist")
    return Dataset.sanitized_dict(ds), 200

@bp.route('/<dataset_name>', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_by_name(dataset_name):
    """
    GET /datasets/id endpoint. Gets dataset with a give id
    """
    ds = get_dataset_by_name(dataset_name)
    if ds is None:
        raise DBRecordNotFoundError(f"Dataset {dataset_name} does not exist")
    return Dataset.sanitized_dict(ds), 200

@bp.route('/<dataset_name>/catalogue', methods=['GET'])
@bp.route('/<int:dataset_id>/catalogue', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_catalogue_by_id(dataset_id=None, dataset_name=None):
    """
    GET /datasets/dataset_name/catalogue endpoint. Gets dataset's catalogue
    GET /datasets/id/catalogue endpoint. Gets dataset's catalogue
    """
    if dataset_name:
        dataset_id = get_dataset_by_name(dataset_name).id

    cata = Catalogue.query.filter(Catalogue.dataset_id == dataset_id).one_or_none()
    if not cata:
        raise DBRecordNotFoundError(f"Dataset {dataset_id} has no catalogue.")
    return cata.sanitized_dict(), 200

@bp.route('/<dataset_name>/dictionaries', methods=['GET'])
@bp.route('/<int:dataset_id>/dictionaries', methods=['GET'])
@audit
@auth(scope='can_access_dataset')
def get_datasets_dictionaries_by_id(dataset_id=None, dataset_name=None):
    """
    GET /datasets/dataset_name/dictionaries endpoint.
    GET /datasets/id/dictionaries endpoint.
        Gets the dataset's list of dictionaries
    """
    if dataset_name:
        dataset_id = get_dataset_by_name(dataset_name).id

    dictionary = Dictionary.query.filter(Dictionary.dataset_id == dataset_id).all()
    if not dictionary:
        raise DBRecordNotFoundError(f"Dataset {dataset_id} has no dictionaries.")

    return [dc.sanitized_dict() for dc in dictionary], 200


@bp.route('/<dataset_name>/dictionaries/<table_name>', methods=['GET'])
@bp.route('/<int:dataset_id>/dictionaries/<table_name>', methods=['GET'])
@audit
@auth(scope='can_access_dataset')

def get_datasets_dictionaries_table_by_id(table_name, dataset_id=None, dataset_name=None):
    """
    GET /datasets/dataset_name/dictionaries/table_name endpoint.
    GET /datasets/id/dictionaries/table_name endpoint.
        Gets the dataset's table within its dictionaries
    """
    if dataset_name:
        dataset_id = get_dataset_by_name(dataset_name).id

    dictionary = Dictionary.query.filter(
        Dictionary.dataset_id == dataset_id,
        Dictionary.table_name == table_name
    ).all()
    if not dictionary:
        raise DBRecordNotFoundError(
            f"Dataset {dataset_id} has no dictionaries with table {table_name}."
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

        body["requested_by"] = json.dumps(body["requested_by"])
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

@bp.route('/workspace/token', methods=['POST'])
@audit
@auth(scope='can_transfer_token', check_dataset=False)
def post_workspace_transfer_token():
    """
    POST /datasets/workspace/token endpoint.
        Sends a user's token based on an approved DAR to an approved third-party
    """
    return "WIP", 200

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
