"""
results endpoints:
- GET /projects/<project_id>/results
- GET /projects/<project_id>/results/<id>
- POST /projects/<project_id>/results
- PATCH /projects/<project_id>/results/<id>
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.result import dump_result
from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.task_config import config_changes
from app.helpers.wrappers import audit, auth
from app.models.pull_request_result import PullRequestResult
from app.models.pull_request_result_step import PullRequestResultStep
from app.models.result_state import ResultState
from app.models.project import Project
from app.models.project_results_repository import ProjectResultsRepository
from app.models.task import Task
from app.models.task_status import TaskStatus
from app.models.result import Result
from app.tasks_api import does_user_own_task

bp = Blueprint('results', __name__, url_prefix='/projects')

BASE_FIELDS = {"attempts", "error"}
PULL_REQUEST_FIELDS = {
    "step", "state", "branch", "commit_sha", "number", "url", "merged_at", "merge_commit_sha"
}


def _project_result(project_id: int, result_id: int) -> Result:
    """The project's result: one whose task is in another project does not exist here."""
    result = Result.query.join(Task, Result.task_id == Task.id).filter(
        Result.id == result_id, Task.project_id == project_id
    ).one_or_none()
    if result is None:
        raise DBRecordNotFoundError(f"Result {result_id} does not exist in project {project_id}")
    return result


@bp.route('/<int:project_id>/results', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_results(project_id: int):
    """
    GET /projects/<project_id>/results endpoint. Lists the project's results
    Query params:
        - step: only the pull request results at this step, repeated for several,
          e.g. ?step=PUSHED&step=OPENED (optional)
        - state: only the pull request results in this state, e.g. ?state=FAILED (optional)
        - active_link: ?active_link=true keeps only the results whose link to the results repository is active
          (enabled, not revoked, on an enabled global repository and provider) (optional)
    """
    Project.get_by_id(project_id)
    # step and state are columns of the pull request results
    query = PullRequestResult.query if 'step' in request.args or 'state' in request.args else Result.query
    steps = request.args.getlist('step')
    if steps:
        valid = [s.value for s in PullRequestResultStep]
        for step in steps:
            if step not in valid:
                raise InvalidRequest(f"Invalid step: {step}. Must be one of: {', '.join(valid)}")
        query = query.filter(PullRequestResult.step.in_(steps))
    state = request.args.get('state')
    if state:
        valid = [s.value for s in ResultState]
        if state not in valid:
            raise InvalidRequest(f"Invalid state: {state}. Must be one of: {', '.join(valid)}")
        query = query.filter(PullRequestResult.state == state)
    query = query.join(Task, Result.task_id == Task.id).filter(Task.project_id == project_id)
    results = query.order_by(Result.id).all()
    if request.args.get('active_link') == 'true':
        results = [r for r in results if r.assignment.active]
    return [dump_result(r) for r in results], HTTPStatus.OK


@bp.route('/<int:project_id>/results/<int:result_id>', methods=['GET'])
@audit
@auth(scope='can_exec_task')
def get_result(project_id: int, result_id: int):
    """
    GET /projects/<project_id>/results/<result_id> endpoint. Gets a single result
    """
    result = _project_result(project_id, result_id)
    does_user_own_task(result.task)
    return dump_result(result), HTTPStatus.OK


@bp.route('/<int:project_id>/results', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def post_result(project_id: int):
    """
    POST /projects/<project_id>/results endpoint. Creates the delivery of a task's results to a results
    repository, by pull request. The repository is the global one's id, which the
    project has to be linked to, and the task has to be the project's. If it exists already, that one is returned.
    Otherwise 409 unless the task is SUCCESS. When the project's link is revoked the result is created as final,
    step REVOKED and state FAILED, and nothing is ever delivered for it. When the link is inactive for another
    reason (disabled by the project, or the global repository disabled) the result is created at step UNKNOWN and
    state FAILED, with the error "results link switched off": the delivery retry sensor delivers it once the link
    is active. A task whose configuration changed since it was created (see helpers/task_config) is not delivered:
    its result is created as final, step STALE and state FAILED, with the changes as its error. The checks run in
    that order: revoked, STALE, switched off.
    """
    body = request.json or {}
    for field in ('task_id', 'results_repository_id'):
        if not isinstance(body.get(field), int) or isinstance(body[field], bool):
            raise InvalidRequest(f"{field} is required and must be an integer")

    Project.get_by_id(project_id)
    task = Task.get_by_id(body['task_id'])
    if task.project_id != project_id:
        raise DBRecordNotFoundError(f"Task {task.id} does not exist in project {project_id}")
    does_user_own_task(task)
    # The delivery is tracked against the project's own link to the repository
    assignment = ProjectResultsRepository.query.filter_by(
        project_id=project_id, results_repository_id=body['results_repository_id']
    ).one_or_none()
    if assignment is None:
        raise InvalidRequest(
            f"Results repository {body['results_repository_id']} is not linked to project {project_id}"
        )

    result = Result.query.filter_by(task_id=task.id, results_repository_id=assignment.id).first()
    if result:
        return dump_result(result), HTTPStatus.OK

    if task.status != TaskStatus.SUCCESS.value:
        raise InvalidRequest(f"Task {task.id} is {task.status}, only a SUCCESS task has results", HTTPStatus.CONFLICT)
    if assignment.revoked:
        result = PullRequestResult(
            task_id=task.id, results_repository_id=assignment.id,
            step=PullRequestResultStep.REVOKED.value, state=ResultState.FAILED.value,
            error="results repository link revoked",
        )
        result.add()
        return dump_result(result), HTTPStatus.CREATED
    changes = config_changes(task)
    if changes:
        result = PullRequestResult(
            task_id=task.id, results_repository_id=assignment.id,
            step=PullRequestResultStep.STALE.value, state=ResultState.FAILED.value,
            error=("task configuration changed since the task was created: " + "; ".join(changes))[:1024],
        )
        result.add()
        return dump_result(result), HTTPStatus.CREATED
    if not assignment.active:
        result = PullRequestResult(
            task_id=task.id, results_repository_id=assignment.id,
            step=PullRequestResultStep.UNKNOWN.value, state=ResultState.FAILED.value,
            error="results link switched off",
        )
        result.add()
        return dump_result(result), HTTPStatus.CREATED

    result = PullRequestResult(task_id=task.id, results_repository_id=assignment.id)
    result.add()
    return dump_result(result), HTTPStatus.CREATED


@bp.route('/<int:project_id>/results/<int:result_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_result(project_id: int, result_id: int):
    """
    PATCH /projects/<project_id>/results/<result_id> endpoint. Records the progress of a task's delivery.
    A pull request result's step only moves forward, see PullRequestResult.set_step
    """
    result = _project_result(project_id, result_id)
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
        valid = [s.value for s in ResultState]
        if body['state'] not in valid:
            raise InvalidRequest(f"Invalid state: {body['state']}. Must be one of: {', '.join(valid)}")

    for field in ('attempts', 'number'):
        if field in body and (not isinstance(body[field], int) or isinstance(body[field], bool) or body[field] < 0):
            raise InvalidRequest(f"{field} must be a non-negative integer")

    if 'step' in body:
        result.set_step(body['step'])

    if 'state' in body:
        result.state = body['state']

    if 'merged_at' in body:
        if body['merged_at'] is not None and not isinstance(body['merged_at'], str):
            raise InvalidRequest("merged_at must be an ISO 8601 datetime string")
        try:
            result.merged_at = body['merged_at']
        except ValueError as e:
            raise InvalidRequest(str(e))

    for field in ('attempts', 'number'):
        if field in body:
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
