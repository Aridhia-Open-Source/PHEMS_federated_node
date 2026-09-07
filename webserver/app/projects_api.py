"""
project endpoints:
- GET /projects
- GET /projects/<project_id>
- POST /projects
"""

from http import HTTPStatus
from flask import Blueprint, request

from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.query_filters import parse_query_params
from app.helpers.wrappers import audit, auth
from app.models.project import Project


bp = Blueprint('projects', __name__, url_prefix='/projects')


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_projects():
    """
    GET /projects endpoint.
    """
    return parse_query_params(Project, request.args.copy()), HTTPStatus.OK


@bp.route('/<int:project_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_by_id(project_id: int):
    """
    GET /projects/<project_id> endpoint.
    """
    project = Project.query.filter_by(id=project_id).one_or_none()
    if project is None:
        raise DBRecordNotFoundError("Project not found")
    return project.sanitized_dict(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def create_project():
    """
    POST /projects endpoint.
    """
    body = Project.validate(request.json)
    if Project.query.filter(Project.name == body["name"]).one_or_none():
        raise InvalidRequest(f"Project {body["name"]} already exists", HTTPStatus.CONFLICT)

    project = Project(**body)
    project.add()
    return {"id": project.id}, HTTPStatus.CREATED
