"""
results endpoints:
- GET /results
- GET /results/<id>
- POST /results
- PATCH /results/<id>
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.result import dump_result
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.wrappers import audit, auth
from app.models.pull_request_result import PullRequestResult
from app.models.pull_request_result_state import PullRequestResultState
from app.models.results_repository import ResultsRepository
from app.models.task import Task
from app.models.result import Result
from app.tasks_api import does_user_own_task

bp = Blueprint('results', __name__, url_prefix='/results')

BASE_FIELDS = {"attempts", "error"}
PULL_REQUEST_FIELDS = {
    "state", "branch", "commit_sha", "number", "url", "merged_at", "merge_commit_sha"
}


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_results():
    """
    GET /results endpoint. Lists results
    Query params:
        - state: only the pull request results in this state, repeated for several,
          e.g. ?state=PUSHED&state=OPENED (optional)
    """
    query = Result.query
    states = request.args.getlist('state')
    if states:
        valid = [s.value for s in PullRequestResultState]
        for state in states:
            if state not in valid:
                raise InvalidRequest(f"Invalid state: {state}. Must be one of: {', '.join(valid)}")
        query = PullRequestResult.query.filter(PullRequestResult.state.in_(states))
    return [dump_result(r) for r in query.order_by(Result.id).all()], HTTPStatus.OK


@bp.route('/<int:result_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_result(result_id):
    """
    GET /results/id endpoint. Gets a single result
    """
    result = Result.get_by_id(result_id)
    does_user_own_task(result.task)
    return dump_result(result), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def post_result():
    """
    POST /results endpoint. Creates the delivery of a task's results to a results
    repository, by pull request. If it exists already, that one is returned.
    """
    body = request.json or {}
    for field in ('task_id', 'results_repository_id'):
        if not isinstance(body.get(field), int) or isinstance(body[field], bool):
            raise InvalidRequest(f"{field} is required and must be an integer")

    task = Task.get_by_id(body['task_id'])
    does_user_own_task(task)
    repo = ResultsRepository.get_by_id(body['results_repository_id'])

    result = Result.query.filter_by(task_id=task.id, results_repository_id=repo.id).first()
    if result:
        return dump_result(result), HTTPStatus.OK

    result = PullRequestResult(task_id=task.id, results_repository_id=repo.id)
    result.add()
    return dump_result(result), HTTPStatus.CREATED


@bp.route('/<int:result_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_result(result_id):
    """
    PATCH /results/id endpoint. Records the progress of a task's delivery.
    A pull request result's state only moves forward, see PullRequestResult.set_state
    """
    result = Result.get_by_id(result_id)
    does_user_own_task(result.task)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    allowed = BASE_FIELDS
    if isinstance(result, PullRequestResult):
        allowed = BASE_FIELDS | PULL_REQUEST_FIELDS
    unknown = set(body) - allowed
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")

    if 'state' in body:
        result.set_state(body['state'])

    if 'merged_at' in body:
        if body['merged_at'] is not None and not isinstance(body['merged_at'], str):
            raise InvalidRequest("merged_at must be an ISO 8601 datetime string")
        try:
            result.merged_at = body['merged_at']
        except ValueError as e:
            raise InvalidRequest(str(e))

    for field in ('attempts', 'number'):
        if field in body:
            if not isinstance(body[field], int) or isinstance(body[field], bool):
                raise InvalidRequest(f"{field} must be an integer")
            setattr(result, field, body[field])

    for field, size in (
        ('branch', 256), ('commit_sha', 40), ('url', 4096), ('merge_commit_sha', 40),
        ('error', 1024)
    ):
        if field in body:
            if body[field] is not None and (not isinstance(body[field], str) or len(body[field]) > size):
                raise InvalidRequest(f"{field} must be a string of at most {size} characters")
            setattr(result, field, body[field])

    db.session.commit()
    return dump_result(result), HTTPStatus.OK
