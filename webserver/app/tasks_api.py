"""
tasks-related endpoints, under the project that owns the tasks. A task of another project is a 404:
- GET /projects/<project_id>/tasks (page and per_page below 1 are clamped to 1)
- POST /projects/<project_id>/tasks
- POST /projects/<project_id>/tasks/validate
- GET /projects/<project_id>/tasks/<task_id>
- PATCH /projects/<project_id>/tasks/<task_id> (a finished task cannot change status: 409)
- POST /projects/<project_id>/tasks/<task_id>/retry
- POST /projects/<project_id>/tasks/<task_id>/cancel
- GET /projects/<project_id>/tasks/<task_id>/results
- POST /projects/<project_id>/tasks/<task_id>/results/approve
- POST /projects/<project_id>/tasks/<task_id>/results/block
- GET /projects/<project_id>/tasks/<task_id>/logs
- GET /projects/<project_id>/tasks/<task_id>/trigger (the pull request that yielded the task, 404 if none)
"""
from datetime import datetime as dt
from http import HTTPStatus

from flask import Blueprint, request
from sqlalchemy import text

from app.helpers.base_model import db
from app.helpers.exceptions import (
    DBRecordNotFoundError, InvalidDBEntry, InvalidRequest, NotImplementedException, TaskImageException,
    UnauthorizedError
)
from app.helpers.keycloak import Keycloak
from app.helpers.query_filters import arg_get
from app.dtos.task_spec import TaskSpecRequest
from app.helpers.wrappers import audit, auth
from app.dtos.task import NewTaskDTO, TaskDTO
from app.dtos.trigger_repository import TaskTriggerDTO
from app.dtos.result import dump_result
from app.models.api_request_trigger import ApiRequestTrigger
from app.models.project import Project
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.task import Task
from app.models.task_status import TaskStatus
from app.models.trigger_state import TriggerState

bp = Blueprint('tasks', __name__, url_prefix='/projects/<int:project_id>/tasks')

# What a task request that fails validation raises. Such a request is kept, as REJECTED.
VALIDATION_ERRORS = (
    InvalidRequest, InvalidDBEntry, DBRecordNotFoundError, TaskImageException, UnauthorizedError
)

# A task in one of these statuses has finished; PATCH cannot change it to another status
FINAL_STATUSES = (TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELED.value)


def does_user_own_task(task: Task):
    """
    Simple wrapper to check if the user is the one who
    triggered the task, or is admin, or is the system user (Dagster, which reads tasks it
    did not request).

    If they don't, an exception is raised with 403 status code
    """
    kc_client = Keycloak()
    token = kc_client.get_token_from_headers()
    dec_token = kc_client.decode_token(token)
    user_id = kc_client.get_user_by_email(dec_token["email"])["id"]

    # TODO(auth): revisit with the Keycloak/authorization rework.
    if (
        task.requested_by != user_id
        and not kc_client.is_user_admin(token)
        and not kc_client.is_system_user(token)
    ):
        raise UnauthorizedError("User does not have enough permissions")


def get_project_task(project_id: int, task_id: int) -> Task:
    """The task, which is a 404 if it belongs to another project."""
    task = Task.get_by_id(task_id)
    if task.project_id != project_id:
        raise DBRecordNotFoundError(f"Task with id {task_id} does not exist in project {project_id}")
    return task


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_task')
def get_tasks(project_id):
    """
    GET /projects/<project_id>/tasks endpoint. Gets the project's tasks with pagination
    Query params:
        - page: page number (default 1, below 1 is clamped to 1)
        - per_page: items per page (default 10, below 1 is clamped to 1)
        - status: filter by task status (optional)
    """
    page = max(arg_get('page', 1, type=int), 1)
    per_page = max(arg_get('per_page', 10, type=int), 1)
    status = request.args.get('status', None)

    Project.get_by_id(project_id)
    query = Task.query.filter(Task.project_id == project_id)

    if status is not None:
        if status not in [s.value for s in TaskStatus]:
            valid = ', '.join([s.value for s in TaskStatus])
            raise InvalidRequest(f"Invalid status: {status}. Must be one of: {valid}")
        query = query.filter(Task.status == status)

    pagination = query.order_by(Task.id).paginate(page=page, per_page=per_page, error_out=False)
    tasks = [TaskDTO.from_model(t).dump() for t in pagination.items]

    return {
        "tasks": tasks,
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages
    }, HTTPStatus.OK


@bp.route('/<int:task_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_id(project_id, task_id):
    """
    GET /projects/<project_id>/tasks/id endpoint. Gets a single task with status
    """
    task = Task.query.get(task_id)
    if not task or task.project_id != project_id:
        return {"error": "Task not found"}, HTTPStatus.NOT_FOUND

    does_user_own_task(task)

    return TaskDTO.from_model(task).dump(), HTTPStatus.OK


@bp.route('/<int:task_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_task(project_id, task_id):
    """
    PATCH /projects/<project_id>/tasks/id endpoint. Records the progress of a task's run.
    A SUCCESS, FAILED or CANCELED task cannot change to a different status (409); setting the same
    status again is allowed. Only POST /projects/<project_id>/tasks/id/retry moves it back to PENDING.
    """
    task = get_project_task(project_id, task_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    unknown = set(body) - {"status", "dagster_run_id", "exit_code", "state_cause", "started_at", "completed_at"}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")

    if 'status' in body:
        if body['status'] not in [s.value for s in TaskStatus]:
            valid = ', '.join([s.value for s in TaskStatus])
            raise InvalidRequest(f"Invalid status: {body['status']}. Must be one of: {valid}")
        if task.status in FINAL_STATUSES and body['status'] != task.status:
            raise InvalidRequest(
                f"Task {task.id} is {task.status} and cannot change to {body['status']}", HTTPStatus.CONFLICT
            )
        task.status = body['status']

    if 'dagster_run_id' in body:
        if not isinstance(body['dagster_run_id'], str):
            raise InvalidRequest("dagster_run_id must be a string")
        task.dagster_run_id = body['dagster_run_id']

    if 'state_cause' in body:
        if not isinstance(body['state_cause'], str):
            raise InvalidRequest("state_cause must be a string")
        task.state_cause = body['state_cause']

    if 'exit_code' in body:
        if not isinstance(body['exit_code'], int) or isinstance(body['exit_code'], bool):
            raise InvalidRequest("exit_code must be an integer")
        task.exit_code = body['exit_code']

    for field in ('started_at', 'completed_at'):
        if field in body:
            try:
                setattr(task, field, dt.fromisoformat(body[field].rstrip('Z')))
            except (ValueError, AttributeError):
                raise InvalidRequest(f"{field} must be a valid ISO 8601 datetime string")

    db.session.commit()
    return TaskDTO.from_model(task).dump(), HTTPStatus.OK


@bp.route('/<int:task_id>/retry', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def retry_task(project_id, task_id):
    """
    POST /projects/<project_id>/tasks/id/retry endpoint. Queues a failed or canceled task for another attempt
    """
    task = get_project_task(project_id, task_id)

    if task.status not in (TaskStatus.FAILED.value, TaskStatus.CANCELED.value):
        raise InvalidRequest(f"Only a {TaskStatus.FAILED} or {TaskStatus.CANCELED} task can be retried")

    task.status = TaskStatus.PENDING.value
    task.attempt += 1
    task.dagster_run_id = None
    task.started_at = None
    task.completed_at = None
    task.exit_code = None
    task.state_cause = None

    db.session.commit()
    return TaskDTO.from_model(task).dump(), HTTPStatus.OK


@bp.route('/<task_id>/cancel', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def cancel_tasks(project_id, task_id):
    """
    POST /projects/<project_id>/tasks/id/cancel endpoint. Cancels a task either scheduled or running one
    """
    raise NotImplementedException()


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_exec_task')
def post_tasks(project_id):
    """
    POST /projects/<project_id>/tasks endpoint. Creates a new task from API request
    """
    raw_body = request.get_data(as_text=True)
    req_body = request.json or {}
    req_body["project_id"] = project_id

    kc_client = Keycloak()
    token = kc_client.get_token_from_headers()
    dec_token = kc_client.decode_token(token)
    user_id = kc_client.get_user_by_email(dec_token["email"])["id"]

    project = Project.get_by_id(project_id)
    if project.locked:
        raise InvalidRequest(f"Project '{project.name}' is locked", HTTPStatus.CONFLICT)

    # The request is recorded before it is evaluated. A rejected one is kept, with
    # the reason and the raw body: no task is created from it, so nothing can launch.
    api_request = ApiRequestTrigger(project_id=project.id, user_id=user_id)
    api_request.add(commit=False)

    session = db.session
    try:
        api_request.set_spec_raw(raw_body)
        session.commit()
        # Validate the task spec, and normalise it. The dataset it was validated
        # against, if any, is the one the task runs on.
        spec = TaskSpecRequest.from_api_body(req_body)
        req_body["docker_image"] = spec.image
        validated = Task.validate(req_body)
        spec.dataset = validated["dataset"].name if validated["dataset"] else None
        new_task = NewTaskDTO.from_spec(spec, api_request)
    except VALIDATION_ERRORS as error:
        api_request.set_state(TriggerState.REJECTED.value, str(error.description)[:1024])
        session.commit()
        raise

    # The state and the task are one transaction
    api_request.set_state(TriggerState.YIELDED.value, None)
    task = Task(**new_task.model_dump())
    task.add(commit=False)
    session.commit()

    return {
        "id": task.id,
        "api_request_id": api_request.id,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None
    }, HTTPStatus.CREATED


@bp.route('/validate', methods=['POST'])
@audit
@auth(scope='can_exec_task')
def post_tasks_validate(project_id):
    """
    POST /projects/<project_id>/tasks/validate endpoint.
        Allows task definition validation without creating the task
    """
    Project.get_by_id(project_id)
    req_body = request.json
    req_body["project_id"] = project_id
    spec = TaskSpecRequest.from_api_body(req_body)
    req_body["docker_image"] = spec.image
    Task.validate(req_body)
    return "Ok", 200


@bp.route('/<int:task_id>/trigger', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_trigger(project_id, task_id):
    """
    GET /projects/<project_id>/tasks/id/trigger endpoint. The pull request that yielded the task,
    with its trigger repository. A task created by hand has none: 404
    """
    task = get_project_task(project_id, task_id)
    does_user_own_task(task)
    if not isinstance(task.trigger, PullRequestTrigger):
        raise DBRecordNotFoundError(f"Task with id {task_id} has no pull request trigger")
    return TaskTriggerDTO.from_model(task.trigger).dump(), HTTPStatus.OK


@bp.route('/<int:task_id>/results', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_results(project_id, task_id):
    """
    GET /projects/<project_id>/tasks/id/results endpoint. Lists the delivery of the task's results
    to each of its destinations
    """
    task = get_project_task(project_id, task_id)
    does_user_own_task(task)
    return [dump_result(r) for r in task.results], HTTPStatus.OK


@bp.route('/<task_id>/logs', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_tasks_logs(project_id: int, task_id: int):
    """
    From a given task, return its logs
    """
    raise NotImplementedException()


@bp.route('/<task_id>/results/approve', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def approve_results(project_id, task_id):
    """
    POST /projects/<project_id>/tasks/id/results/approve endpoint.
        Approves the release (automatic or manual) of
        a task's results
    """
    raise NotImplementedException()


@bp.route('/<task_id>/results/block', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def block_results(project_id, task_id):
    """
    POST /projects/<project_id>/tasks/id/results/block endpoint.
        Blocks the release (automatic or manual) of
        a task's results
    """
    raise NotImplementedException()
