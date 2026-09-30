"""
task results endpoints:
- GET /task_results/<id>
"""
from http import HTTPStatus

from flask import Blueprint

from app.dtos.task_result import TaskResultDTO
from app.helpers.wrappers import audit, auth
from app.models.task_result import TaskResult
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
