"""
tasks-related endpoints:
- GET /tasks/service-info
- GET /tasks
- POST /tasks
- POST /tasks/validate
- GET /tasks/id
- POST /tasks/id/cancel
"""
from flask import Blueprint, request, send_file

from .helpers.exceptions import DBRecordNotFoundError
from .helpers.wrappers import audit, auth
from .helpers.db import db
from .helpers.query_filters import parse_query_params
from .models.task import Task

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
@auth(scope='can_admin_task')
def get_task_id(task_id):
    """
    GET /tasks/id endpoint. Gets a single task
    """
    task = session.get(Task, task_id)
    if task is None:
        raise DBRecordNotFoundError(f"Dataset with id {task_id} does not exist")
    task_dict = task.sanitized_dict()
    task_dict["status"] = task.get_status()
    return task_dict, 200

@bp.route('/<task_id>/cancel', methods=['POST'])
@audit
@auth(scope='can_admin_task')
def cancel_tasks(task_id):
    """
    POST /tasks/id/cancel endpoint. Cancels a task either scheduled or running one
    """
    task = session.get(Task, task_id)
    if task is None:
        raise DBRecordNotFoundError(f"Task with id {task_id} does not exist")

    # Should remove pod/stop ML pipeline
    return task.terminate_pod(), 201

@bp.route('/', methods=['POST'])
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
        Allows to get tasks results
    """
    task = session.get(Task, task_id)
    if task is None:
        raise DBRecordNotFoundError(f"Dataset with id {task_id} does not exist")

    results_file = task.get_results()
    return send_file(results_file, download_name="results.tar.gz"), 200
