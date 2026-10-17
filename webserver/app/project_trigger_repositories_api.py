"""
A project's trigger repositories: its links to the global repositories, and its triggers for
the pull requests ingested for each. A link is addressed by the global repository's id. PUT
links one, 201 the first time and 200 after, replacing the project's settings. Dagster calls
the pull request routes (evaluation state). With ?active=true the list has only the active links
(enabled, not revoked, repository enabled).
- GET /projects/<project_id>/repositories/triggers[?active=true]
- GET|PUT|PATCH|DELETE /projects/<project_id>/repositories/triggers/<repository_id>
- GET /projects/<project_id>/repositories/triggers/<repository_id>/pull_requests
- GET /projects/<project_id>/repositories/triggers/<repository_id>/pull_requests/<number>
- PATCH /projects/<project_id>/repositories/triggers/<repository_id>/pull_requests/<number>
- POST /projects/<project_id>/repositories/triggers/<repository_id>/pull_requests/<number>/task
"""
from http import HTTPStatus

from flask import Blueprint, g, request
from sqlalchemy.exc import IntegrityError

from app.dtos.task import NewTaskDTO, TaskDTO
from app.dtos.task_spec import TaskSpecRequest
from app.dtos.trigger_repository import ProjectTriggerRepositoryDTO, PullRequestTriggerDTO
from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, UnauthorizedError
from app.helpers.project_lock import require_drained
from app.helpers.pull_request_fanout import backfill
from app.helpers.query_filters import arg_get
from app.helpers.repository_loop import check_no_loop, normalise_dir
from app.helpers.wrappers import audit, auth
from app.models.project import Project
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request import PullRequest
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.task import Task
from app.models.trigger_repository import TriggerRepository
from app.models.trigger_state import TriggerState

bp = Blueprint('project_trigger_repositories', __name__)
session = db.session

ASSIGNMENT_URL = '/projects/<int:project_id>/repositories/triggers'


def _assignment(project_id: int, repo_id: int) -> ProjectTriggerRepository:
    """The project's link to a global repository, found by the repository's id."""
    assignment = ProjectTriggerRepository.query.filter_by(
        trigger_repository_id=repo_id, project_id=project_id
    ).one_or_none()
    if assignment is None:
        raise DBRecordNotFoundError(f"Trigger repository {repo_id} is not linked to project {project_id}")
    return assignment


def _check_loop(assignment: ProjectTriggerRepository):
    """Refuses the change, rolling it back, if the trigger would watch where results land."""
    try:
        check_no_loop(assignment.trigger_repository.uri)
    except InvalidRequest:
        session.rollback()
        raise


@bp.route(ASSIGNMENT_URL, methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_project_trigger_repositories(project_id: int):
    """
    GET /projects/<project_id>/repositories/triggers — the project's trigger repository
    links, inactive ones included with their flags unless ?active=true, which returns only the
    active ones.
    """
    Project.get_by_id(project_id)
    assignments = ProjectTriggerRepository.query.filter_by(project_id=project_id).order_by(ProjectTriggerRepository.id)
    if request.args.get('active', '').lower() == 'true':
        assignments = [a for a in assignments if a.active]
    return [ProjectTriggerRepositoryDTO.from_model(a).dump() for a in assignments], HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>', methods=['PUT'])
@audit
@auth(scope='can_admin_dataset')
def put_project_trigger_repository(project_id: int, repo_id: int):
    """
    PUT /projects/<project_id>/repositories/triggers/<repo_id> — links a global trigger
    repository to the project, 201, or replaces the project's settings if it is linked already,
    200, which needs the project locked and drained. A new watcher does not touch work in
    flight, so linking needs no lock. Fields left out take their defaults. The cursor is set when
    the link is created, after the latest pull request stored, and stays where it is.
    Body: {"watch_dir": "triggers", "base_branch": "main", "enabled": true}; watch_dir is
    required, the rest optional.
    """
    project = Project.get_by_id(project_id)
    body = request.json or {}
    allowed = {"watch_dir", "base_branch", "enabled"}
    if not set(body) <= allowed or not isinstance(body.get("watch_dir"), str):
        raise InvalidRequest("Provide watch_dir and, optionally, base_branch and enabled")
    if not isinstance(body.get("enabled", True), bool):
        raise InvalidRequest("enabled must be a boolean")
    if "base_branch" in body and not body["base_branch"]:
        raise InvalidRequest("base_branch cannot be empty")
    repo = TriggerRepository.get_by_id(repo_id)
    watch_dir = normalise_dir(body["watch_dir"])
    assignment = ProjectTriggerRepository.query.filter_by(project_id=project.id, trigger_repository_id=repo.id).one_or_none()

    if assignment is not None:
        require_drained(project)
        was_active = assignment.active
        assignment.watch_dir = watch_dir
        assignment.base_branch = body.get("base_branch", "main")
        assignment.enabled = body.get("enabled", True)
        session.flush()
        _check_loop(assignment)
        session.commit()
        # An assignment that is active now has to catch up on what it missed: after it was enabled
        if assignment.active and not was_active:
            backfill(assignment)
            session.commit()
        return ProjectTriggerRepositoryDTO.from_model(assignment).dump(), HTTPStatus.OK

    assignment = ProjectTriggerRepository(
        project.id, repo.id, watch_dir,
        base_branch=body.get("base_branch", "main"),
        enabled=body.get("enabled", True),
    )
    # History is not replayed: start after the latest pull request stored, or at the link's
    # creation when there is none
    latest = PullRequest.query.filter_by(trigger_repository_id=repo.id)\
        .order_by(PullRequest.merged_at.desc(), PullRequest.number.desc()).first()
    if latest:
        assignment.initial_cursor = latest.merged_at
        assignment.initial_cursor_number = latest.number
    assignment.add(commit=False)
    _check_loop(assignment)
    # Committed first, so the cursor is read back as stored
    session.commit()
    if assignment.active:
        backfill(assignment)
        session.commit()
    return ProjectTriggerRepositoryDTO.from_model(assignment).dump(), HTTPStatus.CREATED


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_project_trigger_repository(project_id: int, repo_id: int):
    """
    GET /projects/<project_id>/repositories/triggers/<repo_id>
    """
    return ProjectTriggerRepositoryDTO.from_model(_assignment(project_id, repo_id)).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_trigger_repository(project_id: int, repo_id: int):
    """
    PATCH /projects/<project_id>/repositories/triggers/<repo_id> — changes what the
    project watches (watch_dir, base_branch) or turns the link on or off
    (enabled), which needs the project locked and drained, or revokes and re-grants it
    (revoked), which is admin only and takes effect at once.
    """
    assignment = _assignment(project_id, repo_id)
    body = request.json or {}
    fields = {"watch_dir", "base_branch", "enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in ("enabled", "revoked"):
        if field in body and not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a trigger repository")

    if set(body) - {"revoked"}:
        require_drained(assignment.project)

    was_active = assignment.active
    if "base_branch" in body:
        if not body["base_branch"]:
            raise InvalidRequest("base_branch cannot be empty")
        assignment.base_branch = body["base_branch"]

    if "watch_dir" in body:
        watch_dir = normalise_dir(body["watch_dir"])
        if not watch_dir:
            raise InvalidRequest("watch_dir cannot be empty")
        assignment.watch_dir = watch_dir

    for field in ("enabled", "revoked"):
        if field in body:
            setattr(assignment, field, body[field])

    session.flush()
    _check_loop(assignment)
    session.commit()
    # An assignment that is active now has to catch up on what it missed: after it was
    # enabled or un-revoked
    if assignment.active and not was_active:
        backfill(assignment)
        session.commit()
    return ProjectTriggerRepositoryDTO.from_model(assignment).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project_trigger_repository(project_id: int, repo_id: int):
    """
    DELETE /projects/<project_id>/repositories/triggers/<repo_id> — unlinks the
    repository, not the repository itself, once the project is locked and drained. Refused while it
    has pull requests.
    """
    assignment = _assignment(project_id, repo_id)
    require_drained(assignment.project)
    try:
        assignment.delete()
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc
    return '', HTTPStatus.NO_CONTENT


def _pull_request(project_id: int, repo_id: int, number: int) -> PullRequestTrigger:
    assignment = _assignment(project_id, repo_id)
    pr = PullRequestTrigger.query.join(PullRequest).filter(
        PullRequestTrigger.project_trigger_repository_id == assignment.id,
        PullRequest.number == number
    ).one_or_none()
    if not pr:
        raise InvalidRequest(
            f"PR #{number} not found in trigger repository {repo_id}", code=HTTPStatus.NOT_FOUND
        )
    return pr


# TODO: the pull_requests routes below are called by Dagster only. No user or admin is
# expected to touch them, so they should be restricted to internal callers.
@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>/pull_requests', methods=['GET'])
@auth(scope='can_admin_dataset')
def get_pull_requests(project_id: int, repo_id: int):
    """
    GET /projects/<project_id>/repositories/triggers/<repo_id>/pull_requests — list PRs
    of an assignment with pagination.
    Query params:
        - page: page number (default 1)
        - per_page: items per page (default 20)
        - state: filter by state (optional), one of: UNKNOWN, REJECTED, YIELDED
        - task_id: only the pull request that yielded this task (optional)
    Sorted by merged_at DESC (most recent first).
    """
    assignment = _assignment(project_id, repo_id)

    page = arg_get('page', 1, type=int)
    per_page = arg_get('per_page', 20, type=int)
    state = request.args.get('state', None)
    task_id = arg_get('task_id', type=int)

    query = PullRequestTrigger.query.join(PullRequest).filter(
        PullRequestTrigger.project_trigger_repository_id == assignment.id
    )

    if state is not None:
        if state not in [s.value for s in TriggerState]:
            valid = ', '.join([s.value for s in TriggerState])
            raise InvalidRequest(f"Invalid state: {state}. Must be one of: {valid}")
        query = query.filter(PullRequestTrigger.state == state)
    if task_id is not None:
        query = query.filter(PullRequestTrigger.task.has(id=task_id))

    query = query.order_by(PullRequest.merged_at.desc(), PullRequest.number.desc())
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [PullRequestTriggerDTO.from_model(pr).dump() for pr in paginated.items],
        'page': paginated.page,
        'per_page': paginated.per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    }, HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>/pull_requests/<int:number>', methods=['GET'])
@auth(scope='can_admin_dataset')
def get_pull_request(project_id: int, repo_id: int, number: int):
    """
    GET /projects/<project_id>/repositories/triggers/<repo_id>/pull_requests/<number> — get a single PR
    """
    pr = _pull_request(project_id, repo_id, number)
    return PullRequestTriggerDTO.from_model(pr).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>/pull_requests/<int:number>', methods=['PATCH'])
@auth(scope='can_admin_dataset')
def patch_pull_request(project_id: int, repo_id: int, number: int):
    """
    PATCH /projects/<project_id>/repositories/triggers/<repo_id>/pull_requests/<number> —
    update PR state and state_cause
    """
    pr = _pull_request(project_id, repo_id, number)

    body = request.json or {}

    if 'state' in body or 'state_cause' in body:
        pr.set_state(body.get('state', pr.state), body.get('state_cause'))

    session.commit()
    return PullRequestTriggerDTO.from_model(pr).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:repo_id>/pull_requests/<int:number>/task', methods=['POST'])
@auth(scope='can_admin_dataset')
def post_task(project_id: int, repo_id: int, number: int):
    """
    POST /projects/<project_id>/repositories/triggers/<repo_id>/pull_requests/<number>/task
    — validate the pull request's spec and, in one transaction, mark it YIELDED and create its
    task. The project comes from the assignment.
    Body: {"spec_raw": "..."}, the pull request's spec file as read. It is kept on the pull
    request before it is parsed, so a rejected pull request keeps it too.
    Idempotent: if the pull request already has a task it is returned with a 200. Only an
    UNKNOWN trigger of an active link may create a task, otherwise 409 (REJECTED is final).
    """
    pr = _pull_request(project_id, repo_id, number)

    if pr.task:
        return TaskDTO.from_model(pr.task).dump(), HTTPStatus.OK
    if pr.state != TriggerState.UNKNOWN.value:
        raise InvalidRequest(f"PR #{number} is {pr.state}, only an UNKNOWN pull request can create a task", HTTPStatus.CONFLICT)
    if not _assignment(project_id, repo_id).active:
        raise InvalidRequest(f"The link to trigger repository {repo_id} is not active", HTTPStatus.CONFLICT)

    body = request.json or {}
    spec_raw = body.get('spec_raw')
    if not isinstance(spec_raw, str):
        raise InvalidRequest("spec_raw is required and must be a string")

    try:
        pr.set_spec_raw(spec_raw)
        session.commit()
        spec = TaskSpecRequest.from_pr_spec(spec_raw)
        # A bad dataset override fails now, before anything is written
        new_task = NewTaskDTO.from_spec(spec, pr)
    except InvalidRequest as error:
        pr.set_state(TriggerState.REJECTED.value, str(error.description)[:1024])
        session.commit()
        raise

    pr.set_state(TriggerState.YIELDED.value, None)
    task = Task(**new_task.model_dump())
    try:
        task.add(commit=False)
        session.commit()
    except IntegrityError:
        # Another call created the task between the check above and this insert
        session.rollback()
        task = Task.query.filter(Task.trigger_id == pr.id).one()
        return TaskDTO.from_model(task).dump(), HTTPStatus.OK
    return TaskDTO.from_model(task).dump(), HTTPStatus.CREATED
