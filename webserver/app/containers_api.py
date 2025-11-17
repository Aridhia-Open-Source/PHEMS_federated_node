"""
containers endpoints:
- GET /containers
- POST /containers
- GET /containers/<id>
- PATCH /containers/<id>
- POST /registries
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
        Registry.url==body["registry"].url
    ).filter(
        (Container.tag==body.get("tag")) | (Container.tag==body.get("sha"))
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

    image = Container.get_by_id(image_id)

    for field in ["ml", "dashboard"]:
        if data.get(field) and isinstance(data.get(field), bool):
            setattr(image, field, data.get(field))

    return {}, HTTPStatus.CREATED


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
    for registry in Registry.query.filter(Registry.active).all():
        for image in registry.fetch_image_list():
            for key in ["tag", "sha"]:
                for tag_or_sha in image[key]:
                    if Container.query.filter(
                        Container.name==image["name"],
                        getattr(Container, key)==tag_or_sha,
                        Container.registry_id==registry.id
                    ).one_or_none():
                        logger.info("Image %s already synched", image["name"])
                        continue
                    if key == "tag":
                        data = Container.validate(
                            {"name": image["name"], "registry": registry.url, "tag": tag_or_sha}
                        )
                    else:
                        data = Container.validate(
                            {"name": image["name"], "registry": registry.url, "sha": tag_or_sha}
                        )
                    cont = Container(**data)
                    cont.add(commit=False)
                    synched.append(cont.full_image_name())
    session.commit()
    return {
        "info": "The sync considers only the latest 100 tag per image. If an older one is needed,"
                " add it manually via the POST /images endpoint",
        "images": synched
        }, HTTPStatus.CREATED
