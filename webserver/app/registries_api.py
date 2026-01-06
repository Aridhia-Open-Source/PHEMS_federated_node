"""
containers endpoints:
- GET /registries
- GET /registries/<registry_id>
- POST /registries
- PATCH /registries/<registry_id>
"""

from http import HTTPStatus
from flask import Blueprint, request

from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import audit, auth
from app.models.registry import Registry


bp = Blueprint('registries', __name__, url_prefix='/registries')


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_registries():
    """
    GET /registries endpoint.
    """
    return Registry.get_all(), HTTPStatus.OK


@bp.route('/<int:registry_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def registry_by_id(registry_id:int):
    """
    GET /registries endpoint.
    """
    registry = Registry.query.filter_by(id=registry_id).one_or_none()
    if registry is None:
        raise DBRecordNotFoundError("Registry not found")
    return registry.sanitized_dict(), HTTPStatus.OK


@bp.route('/<int:registry_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_registry_by_id(registry_id:int):
    """
    GET /registries endpoint.
    """
    registry: Registry = Registry.query.filter_by(id=registry_id).one_or_none()
    if registry is None:
        raise DBRecordNotFoundError("Registry not found")

    registry.delete(commit=True)
    return "", 204


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def add_registry():
    """
    POST /registries endpoint.
    """
    body = Registry.validate(request.json)
    if Registry.query.filter_by(url=body['url']).one_or_none():
        raise InvalidRequest(f"Registry {body['url']} already exist")

    registry = Registry(**body)
    registry.add()
    return {"id": registry.id}, 201


@bp.route('/<int:registry_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_registry(registry_id:int):
    """
    PATCH /registries/<registry_id> endpoint.
    """
    registry = Registry.query.filter(Registry.id == registry_id).one_or_none()
    if registry is None:
        raise InvalidRequest(f"Registry {registry_id} not found")

    registry.update(**request.json)

    return {}, 204
