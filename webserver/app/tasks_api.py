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
from http import HTTPStatus
from flask import Blueprint, request

from app.helpers.exceptions import NotImplementedException, UnauthorizedError
from app.helpers.keycloak import Keycloak
from app.helpers.wrappers import audit, auth
from app.models.task import Task

bp = Blueprint('tasks', __name__, url_prefix='/tasks')


def does_user_own_task(task:Task):
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
    GET /tasks/ endpoint. Gets the list of tasks
    """
    raise NotImplementedException()

@bp.route('/<task_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_id(task_id):
    """
    GET /tasks/id endpoint. Gets a single task
    """
    raise NotImplementedException()

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
    POST /tasks/ endpoint. Creates a new task
    """
    raise NotImplementedException()

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
def get_tasks_logs(task_id:int):
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
