"""
task results endpoints:
- GET /task_results/<id>
- POST /task_results
- PATCH /task_results/<id>
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.task_result import TaskResultDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.wrappers import audit, auth
from app.models.results_repository import ResultsRepository
from app.models.task import Task
from app.models.task_result import TaskResult
from app.models.task_result_status import TaskResultStatus
from app.tasks_api import does_user_own_task

bp = Blueprint('task_results', __name__, url_prefix='/task_results')


@bp.route('/<int:task_result_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_task_result(task_result_id):
    """
    GET /task_results/id endpoint. Gets a single task result
    """
    task_result = TaskResult.get_by_id(task_result_id)
    does_user_own_task(task_result.task)
    return TaskResultDTO.from_model(task_result).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def post_task_result():
    """
    POST /task_results endpoint. Creates the delivery of a task's results to a results
    repository. If it exists already, that one is returned.
    """
    body = request.json or {}
    for field in ('task_id', 'results_repository_id'):
        if not isinstance(body.get(field), int) or isinstance(body[field], bool):
            raise InvalidRequest(f"{field} is required and must be an integer")

    task = Task.get_by_id(body['task_id'])
    does_user_own_task(task)
    repo = ResultsRepository.get_by_id(body['results_repository_id'])

    task_result = TaskResult.query.filter_by(task_id=task.id, results_repository_id=repo.id).first()
    if task_result:
        return TaskResultDTO.from_model(task_result).dump(), HTTPStatus.OK

    task_result = TaskResult(task_id=task.id, results_repository_id=repo.id)
    task_result.add()
    return TaskResultDTO.from_model(task_result).dump(), HTTPStatus.CREATED


@bp.route('/<int:task_result_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_task_result(task_result_id):
    """
    PATCH /task_results/id endpoint. Records the progress of a task's delivery
    """
    task_result = TaskResult.get_by_id(task_result_id)
    does_user_own_task(task_result.task)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    unknown = set(body) - {
        "status", "attempts", "branch", "commit_sha", "pull_request_number", "pull_request_url", "error"
    }
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")

    if 'status' in body:
        if body['status'] not in [s.value for s in TaskResultStatus]:
            valid = ', '.join([s.value for s in TaskResultStatus])
            raise InvalidRequest(f"Invalid status: {body['status']}. Must be one of: {valid}")
        task_result.status = body['status']

    for field in ('attempts', 'pull_request_number'):
        if field in body:
            if not isinstance(body[field], int) or isinstance(body[field], bool):
                raise InvalidRequest(f"{field} must be an integer")
            setattr(task_result, field, body[field])

    for field, size in (
        ('branch', 256), ('commit_sha', 40), ('pull_request_url', 4096), ('error', 1024)
    ):
        if field in body:
            if body[field] is not None and (not isinstance(body[field], str) or len(body[field]) > size):
                raise InvalidRequest(f"{field} must be a string of at most {size} characters")
            setattr(task_result, field, body[field])

    db.session.commit()
    return TaskResultDTO.from_model(task_result).dump(), HTTPStatus.OK
