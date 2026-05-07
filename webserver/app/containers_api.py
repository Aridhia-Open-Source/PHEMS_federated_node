"""
containers endpoints:
- GET /containers
- POST /containers
- GET /containers/<id>
"""
import logging
from http import HTTPStatus
from flask import Blueprint, request

from .helpers.query_filters import parse_query_params

from .helpers.base_model import db
from .helpers.exceptions import InvalidRequest
from .helpers.wrappers import audit, auth
from .models.container import Container
from .models.registry import Registry
from .helpers.const import ENABLE_IMAGE_WHITELIST


bp = Blueprint('containers', __name__, url_prefix='/containers')

logger = logging.getLogger('containers_api')
logger.setLevel(logging.INFO)
session = db.session

@bp.before_request
def check_validation_enabled():
    """
    Check if container validation is enabled before processing any request.
    """
    if not ENABLE_IMAGE_WHITELIST:
        return {"error": "Container validation is disabled"}, HTTPStatus.FORBIDDEN
    return None

@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
def get_all_containers():
    """
    GET /containers endpoint.
        Returns the list of allowed containers
    """
    return parse_query_params(Container, request.args.copy()), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def add_image():
    """
    POST /containers endpoint.
    """
    body = Container.validate(request.json)
    if not (body.get("tag") or body.get("sha")):
        raise InvalidRequest("Make sure `tag` or `sha` are provided")

    # Make sure it doesn't exist already
    existing_image = Container.query.filter(
        Container.name == body["name"],
        Registry.url == body["registry"].url
    ).filter(
        (Container.tag==body.get("tag")) & (Container.sha==body.get("sha"))
    ).join(Registry).one_or_none()

    if existing_image:
        raise InvalidRequest(
            f"Image {body["name"]}:{body["tag"]} already exists in registry {body["registry"].url}",
            409
        )

    image = Container(**body)
    image.add()
    return {"id": image.id}, HTTPStatus.CREATED


@bp.route('/<int:image_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_image_by_id(image_id:int=None):
    """
    GET /containers/<image_id>
    """
    image = Container.get_by_id(image_id)

    return Container.sanitized_dict(image), HTTPStatus.OK


@bp.route('/<int:image_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_image(image_id:int=None):
    """
    DELETE /containers/<image_id>
    """
    image = Container.get_by_id(image_id)
    image.delete()

    return {"message": f"Image {image_id} deleted successfully"}, HTTPStatus.OK
