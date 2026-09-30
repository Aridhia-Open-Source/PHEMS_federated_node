"""
task request endpoints (used by dagster to launch queued task requests):
- GET /task_requests
- GET /task_requests/<id>
- PATCH /task_requests/<id>
- POST /task_requests/<id>/task
"""
from http import HTTPStatus

from flask import Blueprint, request
from sqlalchemy.exc import IntegrityError

from app.dtos.base import page_of
from app.dtos.task import TaskDTO
from app.dtos.trigger_repository import TaskRequestDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.wrappers import auth
from app.models.task import Task
from app.models.task_request import TaskRequest

bp = Blueprint('task_requests', __name__, url_prefix='/task_requests')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_task_requests():
    """
    GET /task_requests/ — list task requests with pagination.
    Query params:
        - page: page number (default 1)
        - per_page: items per page (default 25)
        - queued: true or false (optional)
        - project_id: filter by project (optional)
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    queued = request.args.get('queued', None)
    project_id = request.args.get('project_id', None, type=int)

    query = TaskRequest.query

    if queued is not None:
        if queued not in ('true', 'false'):
            raise InvalidRequest(f"Invalid queued: {queued}. Must be one of: true, false")
        query = query.filter(TaskRequest.queued == (queued == 'true'))

    if project_id is not None:
        query = query.filter(TaskRequest.project_id == project_id)

    query = query.order_by(TaskRequest.id)
    return page_of(query.paginate(page=page, per_page=per_page), TaskRequestDTO), HTTPStatus.OK


@bp.route('/<int:task_request_id>', methods=['GET'])
def get_task_request(task_request_id):
    """
    GET /task_requests/<id> — get a single task request
    """
    task_request = TaskRequest.get_by_id(task_request_id)
    return TaskRequestDTO.from_model(task_request).dump(), HTTPStatus.OK


@bp.route('/<int:task_request_id>', methods=['PATCH'])
def patch_task_request(task_request_id):
    """
    PATCH /task_requests/<id> — set whether the task request is waiting to be launched
    """
    task_request = TaskRequest.get_by_id(task_request_id)

    body = request.json or {}
    if "queued" not in body:
        raise InvalidRequest("No fields provided to update")
    if not isinstance(body["queued"], bool):
        raise InvalidRequest("queued must be a boolean")

    task_request.queued = body["queued"]
    session.commit()
    return TaskRequestDTO.from_model(task_request).dump(), HTTPStatus.OK


@bp.route('/<int:task_request_id>/task', methods=['POST'])
def post_task(task_request_id):
    """
    POST /task_requests/<id>/task — create the task for a task request.
    Idempotent: if the task already exists it is returned with a 200.
    """
    task_request = TaskRequest.get_by_id(task_request_id)

    if task_request.task:
        return TaskDTO.from_model(task_request.task).dump(), HTTPStatus.OK

    task = Task.from_task_request(task_request)
    try:
        task.add()
    except IntegrityError:
        # Another call created the task between the check above and this insert
        session.rollback()
        task = Task.query.filter(Task.task_request_id == task_request_id).one()
        return TaskDTO.from_model(task).dump(), HTTPStatus.OK
    return TaskDTO.from_model(task).dump(), HTTPStatus.CREATED
