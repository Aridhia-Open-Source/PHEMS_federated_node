"""
tasks-related endpoints:
- GET /tasks/service-info
- GET /tasks
- POST /tasks
- POST /tasks/validate
- GET /tasks/id
- POST /tasks/id/cancel
"""
from datetime import datetime
from flask import Blueprint, request
from sqlalchemy import update

from .helpers.exceptions import DBRecordNotFoundError, DBError, InvalidRequest
from .helpers.wrappers import audit, auth
from .helpers.db import db
from .helpers.keycloak import Keycloak
from .helpers.query_filters import parse_query_params
from .helpers.query_validator import validate as validate_query
from .models.dataset import Dataset
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
    return Task.sanitized_dict(task), 200

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
    query = update(Task).where(Task.id == task_id).values(
        status='cancelled',
        updated_at=datetime.now()
        )
    try:
        session.execute(query)
        session.commit()
        return Task.sanitized_dict(task), 201
    except Exception as exc:
        raise DBError("An error occurred while updating") from exc

@bp.route('/', methods=['POST'])
@audit
@auth(scope='can_exec_task')
def post_tasks():
    """
    POST /tasks/ endpoint. Creates a new task
    """
    try:
        body = request.json
        body["requested_by"] = Keycloak().decode_token(
            Keycloak.get_token_from_headers(request.headers)
        ).get('sub')
        body = Task.validate(request.json)

        ds_id = body.pop("dataset_id")
        body["dataset"] = session.get(Dataset, ds_id)
        if body["dataset"] is None:
            raise DBRecordNotFoundError(f"Dataset {ds_id} not found")

        query = body.pop('use_query')
        if not validate_query(query, body["dataset"]):
            raise InvalidRequest("Query missing or misformed")

        task = Task(**body)
        task.can_image_be_found()

        task.add()
        # Create pod/start ML pipeline
        return {"task_id": task.id}, 201
    except:
        session.rollback()
        raise

@bp.route('/validate', methods=['POST'])
@audit
@auth(scope='can_exec_task')
def post_tasks_validate():
    """
    POST /tasks/validate endpoint.
        Allows task definition validation and the DB query that will be used
    """
    return "WIP", 200
