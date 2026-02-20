"""
containers endpoints:
- GET /registries
- GET /registries/<registry_id>
- POST /registries
- PATCH /registries/<registry_id>
"""

from http import HTTPStatus
from flask import Blueprint, request
from pydantic import ValidationError

from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import audit, auth
from app.models.registry import Registry
from app.schemas.pagination import PageResponse
from app.schemas.registries import RegistryCreate, RegistryFilters, RegistryRead, RegistryUpdate
from app.helpers.query_filters import apply_filters
from app.services.registries import RegistryService

bp = Blueprint('registries', __name__, url_prefix='/registries')


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_registries():
    """
    GET /registries endpoint.
    """
    try:
        filter_params = RegistryFilters(**request.args.to_dict())
    except ValidationError as ve:
        raise InvalidRequest(ve.errors()) from ve

    pagination = apply_filters(Registry, filter_params)
    return PageResponse[RegistryRead].model_validate(pagination).model_dump(), 200


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

    return RegistryRead.model_validate(registry).model_dump(), HTTPStatus.OK


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
    body = RegistryCreate(**request.json)
    registry = RegistryService.add(body)
    return RegistryRead.model_validate(registry).model_dump(), HTTPStatus.CREATED


@bp.route('/<int:registry_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_registry(registry_id:int):
    """
    PATCH /registries/<registry_id> endpoint.
    """
    registry: Registry = Registry.query.filter(Registry.id == registry_id).one_or_none()
    if registry is None:
        raise InvalidRequest(f"Registry {registry_id} not found")

    changes = RegistryUpdate(**request.json).model_dump(exclude_unset=True)
    if not changes:
        raise InvalidRequest("No valid changes detected")

    registry.update(**changes)

    return {}, 204
