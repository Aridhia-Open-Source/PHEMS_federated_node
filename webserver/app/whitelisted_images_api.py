"""
whitelisted image endpoints:
- GET /whitelisted_images
- POST /whitelisted_images
- GET /whitelisted_images/<id>
- DELETE /whitelisted_images/<id>
"""
import logging
from http import HTTPStatus
from flask import Blueprint, request

from .helpers.query_filters import parse_query_params

from .helpers.base_model import db
from .helpers.exceptions import InvalidRequest
from .helpers.wrappers import audit, auth
from .models.whitelisted_image import WhitelistedImage
from .models.registry import Registry
from .helpers.const import ENABLE_IMAGE_WHITELIST


bp = Blueprint('whitelisted_images', __name__, url_prefix='/whitelisted_images')

logger = logging.getLogger('whitelisted_images_api')
logger.setLevel(logging.INFO)
session = db.session


@bp.before_request
def check_validation_enabled():
    """
    Check if image whitelisting is enabled before processing any request.
    """
    if not ENABLE_IMAGE_WHITELIST:
        return {"error": "Image whitelisting is disabled"}, HTTPStatus.FORBIDDEN
    return None


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
def get_all_whitelisted_images():
    """
    GET /whitelisted_images endpoint.
        Returns the list of whitelisted images
    """
    return parse_query_params(WhitelistedImage, request.args.copy()), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def add_image():
    """
    POST /whitelisted_images endpoint.
    """
    body = WhitelistedImage.validate(request.json)
    if not (body.get("tag") or body.get("sha")):
        raise InvalidRequest("Make sure `tag` or `sha` are provided")

    # Make sure it doesn't exist already
    existing_image = WhitelistedImage.query.filter(
        WhitelistedImage.name == body["name"],
        Registry.url == body["registry"].url
    ).filter(
        (WhitelistedImage.tag==body.get("tag")) & (WhitelistedImage.sha==body.get("sha"))
    ).join(Registry).one_or_none()

    if existing_image:
        raise InvalidRequest(
            f"Image {body["name"]}:{body["tag"]} already exists in registry {body["registry"].url}",
            409
        )

    image = WhitelistedImage(**body)
    image.add()
    return {"id": image.id}, HTTPStatus.CREATED


@bp.route('/<int:image_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_image_by_id(image_id: int):
    """
    GET /whitelisted_images/<image_id>
    """
    image = WhitelistedImage.get_by_id(image_id)

    return WhitelistedImage.sanitized_dict(image), HTTPStatus.OK


@bp.route('/<int:image_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_image(image_id: int):
    """
    DELETE /whitelisted_images/<image_id>
    """
    image = WhitelistedImage.get_by_id(image_id)
    image.delete()

    return {"message": f"Image {image_id} deleted successfully"}, HTTPStatus.OK
