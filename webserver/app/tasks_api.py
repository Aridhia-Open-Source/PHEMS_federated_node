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
"""
from datetime import datetime, timedelta
from flask import Blueprint, request, send_file

from app.helpers.const import CLEANUP_AFTER_DAYS, TASK_REVIEW
from app.helpers.exceptions import UnauthorizedError, InvalidRequest
from app.helpers.keycloak import Keycloak
from app.helpers.wrappers import audit, auth
from app.helpers.db import db
from app.helpers.query_filters import parse_query_params
from app.models.task import Task

bp = Blueprint('tasks', __name__, url_prefix='/tasks')
session = db.session

@bp.route('/service-info', methods=['GET'])
@audit
@auth(scope='can_do_admin')
def get_service_info():
    """
    GET /tasks/service-info endpoint. Gets the server info
    """
    return "WIP", 200

@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_task')
def get_tasks():
    """
    GET /tasks/ endpoint. Gets the list of tasks
    """
    query = parse_query_params(Task, request.args.copy())
    res = session.execute(query).all()
    if res:
        res = [r[0].sanitized_dict() for r in res]
    return res, 200

@bp.route('/<task_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_id(task_id):
    """
    GET /tasks/id endpoint. Gets a single task
    """
    task = Task.get_by_id(task_id)

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    kc_client = Keycloak()
    dec_token = kc_client.decode_token(token)

    if task.requested_by != dec_token['sub'] and not kc_client.is_user_admin(token):
        raise UnauthorizedError("User does not have enough permissions")

    return task.sanitized_dict(), 200

@bp.route('/<task_id>/cancel', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def cancel_tasks(task_id):
    """
    POST /tasks/id/cancel endpoint. Cancels a task either scheduled or running one
    """
    task = Task.get_by_id(task_id)

    # Should remove pod/stop ML pipeline
    return task.terminate_pod(), 201

@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_exec_task')
def post_tasks():
    """
    POST /tasks/ endpoint. Creates a new task
    """
    try:
        body = Task.validate(request.json)
        task = Task(**body)
        task.add()
        # Create pod/start ML pipeline
        task.run()
        return {"task_id": task.id}, 201
    except:
        session.rollback()
        raise

@bp.route('/validate', methods=['POST'])
@audit
@auth(scope='can_exec_task', check_dataset=False)
def post_tasks_validate():
    """
    POST /tasks/validate endpoint.
        Allows task definition validation and the DB query that will be used
    """
    Task.validate(request.json)
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
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    kc_client = Keycloak()

    task = Task.get_by_id(task_id)

    if TASK_REVIEW and (not task.review_status and not kc_client.is_user_admin(token)):
        return {"status": task.get_review_status()}, 400

    if task.created_at.date() + timedelta(days=CLEANUP_AFTER_DAYS) <= datetime.now().date():
        return {"error": "Tasks results are not available anymore. Please, run the task again"}, 500

    results_file = task.get_results()
    return send_file(results_file, download_name="results.tar.gz"), 200

@bp.route('/<task_id>/results/approve', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def approve_results(task_id):
    """
    POST /tasks/id/results/approve endpoint.
        Approves the release (automatic or manual) of
        a task's results
    """
    if not TASK_REVIEW:
        raise InvalidRequest("Task reviews are not enabled on this Federated Node")

    task = Task.get_by_id(task_id)
    if task.review_status is not None:
        raise InvalidRequest("Task has been already reviewed")
    task.review_status = True

    return {
        "status": task.get_review_status()
    }, 201

@bp.route('/<task_id>/results/block', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def block_results(task_id):
    """
    POST /tasks/id/results/block endpoint.
        Blocks the release (automatic or manual) of
        a task's results
    """
    if not TASK_REVIEW:
        raise InvalidRequest("Task reviews are not enabled on this Federated Node")

    task = Task.get_by_id(task_id)
    if task.review_status is not None:
        raise InvalidRequest("Task has been already reviewed")

    task.review_status = False

    return {
        "status": task.get_review_status()
    }, 201
