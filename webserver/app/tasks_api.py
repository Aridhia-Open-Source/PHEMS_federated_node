"""
tasks-related endpoints:
- GET /tasks/service-info
- GET /tasks
- POST /tasks
- POST /tasks/validate
- GET /tasks/id
- POST /tasks/id/cancel
- GET /tasks/id/results
- POST /tasks/id/results/approve
- POST /tasks/id/results/block
- GET /tasks/id/logs
"""
from copy import deepcopy
from http import HTTPStatus

from flask import Blueprint, request
from sqlalchemy import text

from app.helpers.base_model import db
from app.helpers.exceptions import NotImplementedException, UnauthorizedError
from app.helpers.keycloak import Keycloak
from app.helpers.task_spec import TaskSpec
from app.helpers.wrappers import audit, auth
from app.dtos.task import TaskDTO
from app.models.api_request import ApiRequest
from app.models.task_request import TaskRequest
from app.models.project import Project
from app.models.task import Task

bp = Blueprint('tasks', __name__, url_prefix='/tasks')


def does_user_own_task(task: Task):
    """
    Simple wrapper to check if the user is the one who
    triggered the task, or is admin.

    If they don't, an exception is raised with 403 status code
    """
    kc_client = Keycloak()
    token = kc_client.get_token_from_headers()
    dec_token = kc_client.decode_token(token)
    user_id = kc_client.get_user_by_email(dec_token["email"])["id"]

    if task.requested_by != user_id and not kc_client.is_user_admin(token):
        raise UnauthorizedError("User does not have enough permissions")


@bp.route('/service-info', methods=['GET'])
@audit
@auth(scope='can_do_admin')
def get_service_info():
    """
    GET /tasks/service-info endpoint. Gets the server info
    """
    return {
        "name": "Federated Node",
        "doc": "Part of the PHEMS network"
    }, HTTPStatus.OK


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_task')
def get_tasks():
    """
    GET /tasks/ endpoint. Gets the list of tasks with pagination
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    pagination = Task.query.paginate(page=page, per_page=per_page)
    tasks = [TaskDTO.from_model(t).dump() for t in pagination.items]

    return {
        "tasks": tasks,
        "total": pagination.total,
        "page": page,
        "per_page": per_page,
        "pages": pagination.pages
    }, HTTPStatus.OK


@bp.route('/<int:task_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_id(task_id):
    """
    GET /tasks/id endpoint. Gets a single task with status
    """
    task = Task.query.get(task_id)
    if not task:
        return {"error": "Task not found"}, HTTPStatus.NOT_FOUND

    does_user_own_task(task)

    return TaskDTO.from_model(task).dump(), HTTPStatus.OK


@bp.route('/<task_id>/cancel', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def cancel_tasks(task_id):
    """
    POST /tasks/id/cancel endpoint. Cancels a task either scheduled or running one
    """
    raise NotImplementedException()


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_exec_task')
def post_tasks():
    """
    POST /tasks/ endpoint. Creates a new task from API request
    """
    req_body = request.json or {}
    raw_body = deepcopy(req_body)
    project_name = request.headers.get("project-name")
    req_body["project_name"] = project_name

    # Validate the task spec, and normalise it. The dataset it was validated
    # against is the one the task runs on.
    validated = Task.validate(req_body)
    spec = TaskSpec.from_api_body(req_body)
    spec.dataset = validated["dataset"].name

    # Create ApiRequest record
    kc_client = Keycloak()
    token = kc_client.get_token_from_headers()
    dec_token = kc_client.decode_token(token)
    user_id = kc_client.get_user_by_email(dec_token["email"])["id"]

    project = Project.query.filter_by(name=project_name).first()
    if not project:
        return {"error": f"Project '{project_name}' not found"}, HTTPStatus.NOT_FOUND

    # The three rows are one transaction: a failure creates none of them
    session = db.session
    try:
        api_request = ApiRequest(
            project_id=project.id,
            user_id=user_id,
            payload=raw_body
        )
        api_request.add(commit=False)

        task_request = TaskRequest(
            api_request_id=api_request.id,
            project_id=project.id,
            payload=spec.model_dump(),
            queued=True,
        )
        task_request.add(commit=False)

        # Create Task from TaskRequest
        task = Task.from_task_request(task_request, requested_by=user_id)
        task.add(commit=False)

        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "id": task.id,
        "api_request_id": api_request.id,
        "task_request_id": task_request.id,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None
    }, HTTPStatus.CREATED


@bp.route('/validate', methods=['POST'])
@audit
@auth(scope='can_exec_task', check_dataset=False)
def post_tasks_validate():
    """
    POST /tasks/validate endpoint.
        Allows task definition validation without creating the task
    """
    req_body = request.json
    req_body["project_name"] = request.headers.get("project-name")
    Task.validate(req_body)
    TaskSpec.from_api_body(req_body)
    return "Ok", 200


@bp.route('/<task_id>/results', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_results(task_id):
    """
    GET /tasks/id/results endpoint.
        Allows to get tasks results if approved to be released
        or, if an admin is trying to view them
    """
    raise NotImplementedException()


@bp.route('/<task_id>/logs', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_tasks_logs(task_id: int):
    """
    From a given task, return its logs
    """
    raise NotImplementedException()


@bp.route('/<task_id>/results/approve', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def approve_results(task_id):
    """
    POST /tasks/id/results/approve endpoint.
        Approves the release (automatic or manual) of
        a task's results
    """
    raise NotImplementedException()


@bp.route('/<task_id>/results/block', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def block_results(task_id):
    """
    POST /tasks/id/results/block endpoint.
        Blocks the release (automatic or manual) of
        a task's results
    """
    raise NotImplementedException()
