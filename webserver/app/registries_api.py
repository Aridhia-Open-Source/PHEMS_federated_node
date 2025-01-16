"""
containers endpoints:
- GET /registries
- POST /registries
"""

from flask import Blueprint, request

from app.helpers.wrappers import audit, auth
from .models.registry import Registry


bp = Blueprint('registries', __name__, url_prefix='/registries')


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_registries():
    """
    GET /registries endpoint.
    """
    return Registry.get_all(), 200


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def add_registry():
    """
    POST /registries endpoint.
    """
    body = Registry.validate(request.json)
    image = Registry(**body)
    image.add()
    return {"id": image.id}, 201