"""
tasks-related endpoints, under the project that owns the tasks. A task of another project is a 404:
- GET /tasks (the tasks of all projects; status, comma separated; project_enabled=true; page and per_page as below)
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
- GET /projects/<project_id>/tasks/<task_id>/config (whether the configuration the task was created under still holds)
- POST /projects/<project_id>/tasks/<task_id>/launch (the launcher's one call: decides, fails the task or returns the run inputs; a task not PENDING: 409)
"""
from datetime import datetime as dt
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import PlainTextResponse

from app.helpers.base_model import db, paginate
from app.helpers.const import TASK_CAUSE_MAX_LENGTH
from app.helpers.exceptions import (
    DBRecordNotFoundError, InvalidDBEntry, InvalidRequest, NotImplementedException, TaskImageException,
    UnauthorizedError
)
from app.helpers.keycloak import Keycloak  # noqa: F401  patched by tests/conftest.py
from app.helpers.project_state import require_accepts_tasks
from app.helpers.state_rules import transition
from app.helpers.query_filters import QueryFilters, arg_get
from app.helpers.task_config import decide_launch
from app.dtos.task_spec import TaskSpecRequest
from app.helpers.wrappers import Caller, get_caller, require_scope, system_only
from app.dtos.dataset import DatasetDTO
from app.dtos.task import NewTaskDTO, TaskDTO
from app.dtos.trigger_repository import TaskTriggerDTO
from app.dtos.result import dump_result
from app.models.api_request_trigger import ApiRequestTrigger
from app.models.project import Project
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.task import Task
from app.models.task_status import RETRYABLE, TASK_MOVES, TaskStatus
from app.models.trigger_state import TriggerState

router = APIRouter(prefix='/projects/{project_id}/tasks', tags=["tasks"])
all_router = APIRouter(prefix='/tasks', tags=["tasks"])

# What a task request that fails validation raises. Such a request is kept, as REJECTED.
VALIDATION_ERRORS = (
    InvalidRequest, InvalidDBEntry, DBRecordNotFoundError, TaskImageException, UnauthorizedError
)


def does_user_own_task(task: Task, caller: Caller):
    """
    Simple wrapper to check if the user is the one who
    triggered the task, or is admin, or is the system user (Dagster, which reads tasks it
    did not request).

    If they don't, an exception is raised with 403 status code
    """
    # TODO(auth): revisit with the Keycloak/authorization rework.
    if task.requested_by != caller.user_id and not caller.is_admin and not caller.is_system:
        raise UnauthorizedError("User does not have enough permissions")


def get_project_task(project_id: int, task_id: int) -> Task:
    """The task, which is a 404 if it belongs to another project or the project is deleted."""
    Project.get_by_id(project_id)
    task = Task.get_by_id(task_id)
    if task.project_id != project_id:
        raise DBRecordNotFoundError(f"Task with id {task_id} does not exist in project {project_id}")
    return task


async def raw_body(request: Request) -> str:
    """The request body as it was sent, which a task request keeps."""
    return (await request.body()).decode()


@router.get('/', dependencies=[Depends(require_scope('can_admin_task'))])
@router.get('', dependencies=[Depends(require_scope('can_admin_task'))])
def get_tasks(project_id: int, filters: QueryFilters = Depends(), status: str | None = None):
    """
    GET /projects/<project_id>/tasks endpoint. Gets the project's tasks with pagination
    Query params:
        - page: page number (default 1, below 1 is clamped to 1)
        - per_page: items per page (default 10, below 1 is clamped to 1)
        - status: filter by task status (optional)
    """
    Project.get_by_id(project_id)
    query = Task.query.filter(Task.project_id == project_id)
    return task_page(query, parse_statuses(status), filters)


@all_router.get('/', dependencies=[Depends(require_scope('can_admin_task'))])
@all_router.get('', dependencies=[Depends(require_scope('can_admin_task'))])
def get_all_tasks(filters: QueryFilters = Depends(), status: str | None = None, project_enabled: str | None = None):
    """
    GET /tasks endpoint. Gets the tasks of all projects with pagination, ordered by id, in the shape of
    GET /projects/<project_id>/tasks. Query params:
        - page, per_page: as the project's list
        - status: one or more task statuses, comma separated (optional)
        - project_enabled: "true" keeps the tasks of enabled projects, as GET /projects?enabled=true
          lists them. A revoked project is still enabled, so its tasks stay.
    """
    query = Task.query
    if project_enabled is not None:
        if project_enabled not in ('true', 'false'):
            raise InvalidRequest("project_enabled should be true or false")
        if project_enabled == 'true':
            query = query.filter(Task.project_id.in_(Project.query.filter(Project.enabled.is_(True)).with_entities(Project.id)))
    return task_page(query, parse_statuses(status), filters)


def parse_statuses(raw: str | None) -> list[str] | None:
    """The statuses of a comma separated `status` parameter, 400 listing the valid ones if one is not."""
    if raw is None:
        return None
    valid = [s.value for s in TaskStatus]
    statuses = [s.strip() for s in raw.split(',')]
    for status in statuses:
        if status not in valid:
            raise InvalidRequest(f"Invalid status: {status}. Must be one of: {', '.join(valid)}")
    return statuses


def task_page(query, statuses: list[str] | None, filters: QueryFilters) -> dict:
    """A page of the query's tasks, filtered by status and ordered by id, per the page and per_page parameters."""
    page = max(arg_get(filters, 'page', 1, type=int), 1)
    per_page = max(arg_get(filters, 'per_page', 10, type=int), 1)
    if statuses is not None:
        query = query.filter(Task.status.in_(statuses))
    pagination = paginate(query.order_by(Task.id), page, per_page)
    return {
        "tasks": [TaskDTO.from_model(t).dump() for t in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages
    }


@router.get('/{task_id}', response_model=TaskDTO, dependencies=[Depends(require_scope('can_exec_task'))])
def get_task_id(project_id: int, task_id: int, caller: Caller = Depends(get_caller)):
    """
    GET /projects/<project_id>/tasks/id endpoint. Gets a single task with status
    """
    Project.get_by_id(project_id)
    task = Task.query.get(task_id)
    if not task or task.project_id != project_id:
        raise DBRecordNotFoundError("Task not found")

    does_user_own_task(task, caller)

    return TaskDTO.from_model(task)


@router.patch(
    '/{task_id}', response_model=TaskDTO,
    dependencies=[Depends(require_scope('can_admin_dataset')), Depends(system_only)]
)
def patch_task(project_id: int, task_id: int, body: dict = Body(default_factory=dict)):
    """
    PATCH /projects/<project_id>/tasks/id endpoint. Records the progress of a task's run.
    A move not in TASK_MOVES is a 409, e.g. out of SUCCESS, FAILED or CANCELED; setting the same
    status again is allowed. Only POST /projects/<project_id>/tasks/id/retry moves it back to PENDING.
    """
    task = get_project_task(project_id, task_id)

    if not body:
        raise InvalidRequest("No fields provided to update")

    unknown = set(body) - {"status", "executor_run_id", "exit_code", "state_cause", "started_at", "completed_at"}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")

    if 'status' in body:
        if body['status'] not in [s.value for s in TaskStatus]:
            valid = ', '.join([s.value for s in TaskStatus])
            raise InvalidRequest(f"Invalid status: {body['status']}. Must be one of: {valid}")
        transition(TASK_MOVES, task.status, body['status'])
        task.status = body['status']

    if 'executor_run_id' in body:
        if not isinstance(body['executor_run_id'], str):
            raise InvalidRequest("executor_run_id must be a string")
        task.executor_run_id = body['executor_run_id']

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
    return TaskDTO.from_model(task)


@router.post('/{task_id}/retry', response_model=TaskDTO, dependencies=[Depends(require_scope('can_admin_task'))])
def retry_task(project_id: int, task_id: int):
    """
    POST /projects/<project_id>/tasks/id/retry endpoint. Queues a failed or canceled task for another attempt
    """
    task = get_project_task(project_id, task_id)

    if task.status not in RETRYABLE:
        raise InvalidRequest(f"Only a {TaskStatus.FAILED} or {TaskStatus.CANCELED} task can be retried")

    task.status = TaskStatus.PENDING.value
    task.attempt += 1
    task.executor_run_id = None
    task.started_at = None
    task.completed_at = None
    task.exit_code = None
    task.state_cause = None

    db.session.commit()
    return TaskDTO.from_model(task)


@router.post('/{task_id}/cancel', dependencies=[Depends(require_scope('can_admin_task'))])
def cancel_tasks(project_id: int, task_id: int):
    """
    POST /projects/<project_id>/tasks/id/cancel endpoint. Cancels a task either scheduled or running one
    """
    raise NotImplementedException()


@router.post('/', status_code=HTTPStatus.CREATED, dependencies=[Depends(require_scope('can_exec_task'))])
@router.post('', status_code=HTTPStatus.CREATED, dependencies=[Depends(require_scope('can_exec_task'))])
def post_tasks(
    project_id: int, raw: str = Depends(raw_body), req_body: dict = Body(default_factory=dict),
    caller: Caller = Depends(get_caller)
):
    """
    POST /projects/<project_id>/tasks endpoint. Creates a new task from API request
    """
    req_body["project_id"] = project_id

    project = Project.get_by_id(project_id)
    require_accepts_tasks(project)

    # The request is recorded before it is evaluated. A rejected one is kept, with
    # the reason and the raw body: no task is created from it, so nothing can launch.
    api_request = ApiRequestTrigger(project_id=project.id, user_id=caller.user_id)
    api_request.add(commit=False)

    session = db.session
    try:
        api_request.set_spec_raw(raw)
        session.commit()
        # Validate the task spec, and normalise it. The dataset it was validated
        # against, if any, is the one the task runs on.
        spec = TaskSpecRequest.from_api_body(req_body)
        req_body["docker_image"] = spec.image
        validated = Task.validate(req_body, caller.token)
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
    }


@router.post(
    '/validate', response_class=PlainTextResponse, dependencies=[Depends(require_scope('can_exec_task'))]
)
def post_tasks_validate(project_id: int, req_body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    POST /projects/<project_id>/tasks/validate endpoint.
        Allows task definition validation without creating the task
    """
    Project.get_by_id(project_id)
    req_body["project_id"] = project_id
    spec = TaskSpecRequest.from_api_body(req_body)
    req_body["docker_image"] = spec.image
    Task.validate(req_body, caller.token)
    return "Ok"


@router.get(
    '/{task_id}/trigger', response_model=TaskTriggerDTO, dependencies=[Depends(require_scope('can_exec_task'))]
)
def get_task_trigger(project_id: int, task_id: int, caller: Caller = Depends(get_caller)):
    """
    GET /projects/<project_id>/tasks/id/trigger endpoint. The pull request that yielded the task,
    with its trigger repository. A task created by hand has none: 404
    """
    task = get_project_task(project_id, task_id)
    does_user_own_task(task, caller)
    if not isinstance(task.trigger, PullRequestTrigger):
        raise DBRecordNotFoundError(f"Task with id {task_id} has no pull request trigger")
    return TaskTriggerDTO.from_model(task.trigger)


@router.get('/{task_id}/config', dependencies=[Depends(require_scope('can_exec_task'))])
def get_task_config(project_id: int, task_id: int, caller: Caller = Depends(get_caller)):
    """
    GET /projects/<project_id>/tasks/id/config endpoint. Whether the configuration the task was created
    under (its results repository and target_dir, its dataset) is still the current one. If not, the task
    must not launch or publish, and changes lists what differs. A task without a stored snapshot is current.
    config_snapshot is the pinned configuration itself: delivery takes its target_dir from it, as the link may be deleted by then.
    revoked names what the task uses that is revoked or deleted (its project, trigger, dataset or results repository): such a
    task must not launch either, and its results are never delivered.
    outcome is the decision for a PENDING task, "launch" or "fail", and cause says why when it fails: see
    helpers/task_config.decide_launch for the rules and their order. Read-only, safe to call every tick.
    """
    task = get_project_task(project_id, task_id)
    does_user_own_task(task, caller)
    decision = decide_launch(task)
    return {
        "outcome": decision.outcome, "cause": decision.cause,
        "current": not decision.changes, "changes": decision.changes, "config_hash": task.config_hash,
        "config_snapshot": task.config_snapshot, "revoked": decision.revoked,
    }


@router.post(
    '/{task_id}/launch',
    dependencies=[Depends(require_scope('can_admin_dataset')), Depends(system_only)]
)
def launch_task(project_id: int, task_id: int, caller: Caller = Depends(get_caller)):
    """
    POST /projects/<project_id>/tasks/id/launch endpoint. The launcher's one call per PENDING task. It decides
    with helpers/task_config.decide_launch, the same rules GET .../config reports, and answers:
    - "fail": the task is moved to FAILED here, its state_cause the cause cut to TASK_CAUSE_MAX_LENGTH. Returns
      outcome, cause (as stored) and the failed task.
    - "launch": nothing is written. Returns outcome, the task (spec included) and its dataset, with the secret
      reference, exactly what the run request needs; dataset is null for a task without one.
    A task that is no longer PENDING is a 409 and nothing changes, so a repeated call is safe.
    """
    task = get_project_task(project_id, task_id)
    does_user_own_task(task, caller)
    if task.status != TaskStatus.PENDING.value:
        raise InvalidRequest(f"Task {task_id} is {task.status}, not {TaskStatus.PENDING.value}", HTTPStatus.CONFLICT)

    decision = decide_launch(task)
    if decision.outcome == "fail":
        transition(TASK_MOVES, task.status, TaskStatus.FAILED.value)
        task.status = TaskStatus.FAILED.value
        task.state_cause = (decision.cause or "failed by the backend")[:TASK_CAUSE_MAX_LENGTH]
        db.session.commit()
        return {"outcome": "fail", "cause": task.state_cause, "task": TaskDTO.from_model(task).dump(), "dataset": None}

    dataset = task.spec.dataset if task.spec.dataset_id else None
    return {
        "outcome": "launch", "cause": None, "task": TaskDTO.from_model(task).dump(),
        "dataset": DatasetDTO.from_model(dataset).dump() if dataset else None,
    }


@router.get('/{task_id}/results', dependencies=[Depends(require_scope('can_exec_task'))])
def get_task_results(project_id: int, task_id: int, caller: Caller = Depends(get_caller)):
    """
    GET /projects/<project_id>/tasks/id/results endpoint. Lists the delivery of the task's results
    to each of its destinations
    """
    task = get_project_task(project_id, task_id)
    does_user_own_task(task, caller)
    return [dump_result(r) for r in task.results]


@router.get('/{task_id}/logs', dependencies=[Depends(require_scope('can_exec_task'))])
def get_tasks_logs(project_id: int, task_id: int):
    """
    From a given task, return its logs
    """
    raise NotImplementedException()


@router.post('/{task_id}/results/approve', dependencies=[Depends(require_scope('can_admin_task'))])
def approve_results(project_id: int, task_id: int):
    """
    POST /projects/<project_id>/tasks/id/results/approve endpoint.
        Approves the release (automatic or manual) of
        a task's results
    """
    raise NotImplementedException()


@router.post('/{task_id}/results/block', dependencies=[Depends(require_scope('can_admin_task'))])
def block_results(project_id: int, task_id: int):
    """
    POST /projects/<project_id>/tasks/id/results/block endpoint.
        Blocks the release (automatic or manual) of
        a task's results
    """
    raise NotImplementedException()
