"""
containers endpoints:
- GET /containers
- POST /containers
- GET /containers/<id>
- PATCH /containers/<id>
- POST /registries
"""
import logging
from flask import Blueprint, request

from .helpers.base_model import db
from .helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from .helpers.wrappers import audit, auth
from .models.container import Container
from .models.registry import Registry


bp = Blueprint('containers', __name__, url_prefix='/containers')

logger = logging.getLogger('containers_api')
logger.setLevel(logging.INFO)
session = db.session

@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
def get_all_containers():
    """
    GET /containers endpoint.
        Returns the list of allowed containers
    """
    return Container.get_all(), 200


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def add_image():
    """
    POST /containers endpoint.
    """
    body = Container.validate(request.json)
    # Make sure it doesn't exist already
    existing_image = Container.query.filter(
        Container.name == body["name"],
        Container.tag==body["tag"],
        Registry.url==body["registry"].url
    ).join(Registry).one_or_none()
    if existing_image:
        raise InvalidRequest(
            f"Image {body["name"]}:{body["tag"]} already exists in registry {body["registry"].url}",
            409
        )

    image = Container(**body)
    image.add()
    return {"id": image.id}, 201


@bp.route('/<int:image_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_image_by_id(image_id:int=None):
    """
    GET /containers/<image_id>
    """
    image = Container.query.filter(Container.id == image_id).one_or_none()
    if not image:
        raise DBRecordNotFoundError(f"Container id: {image_id} not found")

    return Container.sanitized_dict(image), 200


@bp.route('/<int:image_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_datasets_by_id_or_name(image_id:int=None):
    """
    PATCH /image/id endpoint. Edits an existing container image with a given id
    """
    if not request.is_json:
        raise InvalidRequest(
            "Request body must be a valid json, or set the Content-Type to application/json",
            400
        )

    data = request.json
    # validation, only ml and dashboard are allowed
    if not (data.get("ml") or data.get("dashboard")):
        raise InvalidRequest("Either `ml` or `dashboard` field must be provided")

    image = Container.query.filter(Container.id == image_id).one_or_none()
    if not image:
        raise DBRecordNotFoundError(f"Container id: {image_id} not found")

    for field in ["ml", "dashboard"]:
        if data.get(field) and isinstance(data.get(field), bool):
            setattr(image, field, data.get(field))

    return {}, 204


@bp.route('/sync', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def sync():
    """
    POST /containers/sync
        syncs up the list of available containers from the
        available registries and adds them to the DB table
        with both dashboard and ml flags to false, effectively
        making them not usable. To "enable" them one of those
        flags has to set to true. This is done to avoid undesirable
        or unintended containers to be used on a node.
    """
    synched = []
    for registry in Registry.query.all():
        for image in registry.fetch_image_list():
            for tag in image["tags"]:
                if Container.query.filter_by(
                    name=image["name"],
                    tag=tag,
                    registry_id=registry.id
                ).one_or_none():
                    logger.info("Image %s already synched", image["name"])
                    continue

                data = Container.validate(
                    {"name": image["name"], "registry": registry.url, "tag": tag}
                )
                cont = Container(**data)
                cont.add(commit=False)
                synched.append(cont.full_image_name())
    session.commit()
    return synched, 201
