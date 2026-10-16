"""
A project's trigger repositories: the assignments of the global repositories, and the pull
requests ingested for each. Dagster calls the pull request routes (polling state) and the
project-spanning list.
- GET /project_trigger_repositories
- GET /projects/<project_id>/trigger_repositories
- POST /projects/<project_id>/trigger_repositories
- GET /projects/<project_id>/trigger_repositories/<assignment_id>
- PATCH /projects/<project_id>/trigger_repositories/<assignment_id>
- DELETE /projects/<project_id>/trigger_repositories/<assignment_id>
- POST /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests
- POST /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/batch
- GET /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests
- GET /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/<number>
- PATCH /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/<number>
- POST /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/<number>/task
"""
from http import HTTPStatus

from flask import Blueprint, g, request
from sqlalchemy.exc import IntegrityError

from app.dtos.task import NewTaskDTO, TaskDTO
from app.dtos.task_spec import TaskSpecRequest
from app.dtos.trigger_repository import ProjectTriggerRepositoryDTO, PullRequestRequest, PullRequestTriggerDTO
from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, UnauthorizedError
from app.helpers.project_lock import require_drained
from app.helpers.pull_request_fanout import backfill, ingest_pull_requests
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

ASSIGNMENT_URL = '/projects/<int:project_id>/trigger_repositories'


def _assignment(project_id: int, assignment_id: int) -> ProjectTriggerRepository:
    assignment = ProjectTriggerRepository.query.filter_by(id=assignment_id, project_id=project_id).one_or_none()
    if assignment is None:
        raise DBRecordNotFoundError(
            f"Trigger repository assignment {assignment_id} not found in project {project_id}"
        )
    return assignment


def _check_loop(assignment: ProjectTriggerRepository):
    """Refuses the change, rolling it back, if the trigger would watch where results land."""
    try:
        check_no_loop(assignment.trigger_repository.uri)
    except InvalidRequest:
        session.rollback()
        raise


@bp.route('/project_trigger_repositories', methods=['GET'])
@auth(scope='can_admin_dataset')
def list_all_assignments():
    """
    GET /project_trigger_repositories — every project's assignments, for Dagster, which polls
    per assignment. Optionally only the active ones (?active=true) or those of enabled
    projects (?project_enabled=true).
    """
    query = ProjectTriggerRepository.query
    if request.args.get('active', '').lower() == 'true':
        query = query.filter(
            ProjectTriggerRepository.enabled.is_(True), ProjectTriggerRepository.revoked.is_(False)
        )
    if request.args.get('project_enabled', '').lower() == 'true':
        query = query.join(Project).filter(Project.enabled.is_(True))
    return [ProjectTriggerRepositoryDTO.from_model(a).dump() for a in query.order_by(ProjectTriggerRepository.id)], HTTPStatus.OK


@bp.route(ASSIGNMENT_URL, methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_project_trigger_repositories(project_id: int):
    """
    GET /projects/<project_id>/trigger_repositories — the project's trigger repository
    assignments, inactive ones included with their flags.
    """
    Project.get_by_id(project_id)
    assignments = ProjectTriggerRepository.query.filter_by(project_id=project_id).order_by(ProjectTriggerRepository.id)
    return [ProjectTriggerRepositoryDTO.from_model(a).dump() for a in assignments], HTTPStatus.OK


@bp.route(ASSIGNMENT_URL, methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def assign_project_trigger_repository(project_id: int):
    """
    POST /projects/<project_id>/trigger_repositories — assigns a global trigger repository to
    the project. A new watcher does not touch work in flight, so no lock is needed.
    Body: {"trigger_repository_id": 1, "watch_dir": "triggers", "base_branch": "main",
    "initial_cursor": "2026-01-01T00:00:00Z", "enabled": true}; watch_dir is required, the
    rest optional.
    """
    project = Project.get_by_id(project_id)
    body = request.json or {}
    allowed = {"trigger_repository_id", "watch_dir", "base_branch", "initial_cursor", "enabled"}
    if not set(body) <= allowed or not isinstance(body.get("trigger_repository_id"), int) \
            or not isinstance(body.get("watch_dir"), str):
        raise InvalidRequest(
            "Provide trigger_repository_id (an integer), watch_dir and, optionally, base_branch, "
            "initial_cursor and enabled"
        )
    if not isinstance(body.get("enabled", True), bool):
        raise InvalidRequest("enabled must be a boolean")
    if "base_branch" in body and not body["base_branch"]:
        raise InvalidRequest("base_branch cannot be empty")
    repo = TriggerRepository.get_by_id(body["trigger_repository_id"])
    watch_dir = normalise_dir(body["watch_dir"])
    if ProjectTriggerRepository.query.filter_by(
        project_id=project.id, trigger_repository_id=repo.id, watch_dir=watch_dir
    ).first():
        raise InvalidRequest(
            f"Repository {repo.uri} is already assigned to project {project.name} for '{watch_dir}'",
            HTTPStatus.CONFLICT
        )

    try:
        assignment = ProjectTriggerRepository(
            project.id, repo.id, watch_dir,
            base_branch=body.get("base_branch", "main"),
            initial_cursor=body.get("initial_cursor"),
            enabled=body.get("enabled", True),
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if "initial_cursor" not in body:
        # History is not replayed: start after the latest pull request stored
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


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_project_trigger_repository(project_id: int, assignment_id: int):
    """
    GET /projects/<project_id>/trigger_repositories/<assignment_id>
    """
    return ProjectTriggerRepositoryDTO.from_model(_assignment(project_id, assignment_id)).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_trigger_repository(project_id: int, assignment_id: int):
    """
    PATCH /projects/<project_id>/trigger_repositories/<assignment_id> — changes what the
    project watches (watch_dir, base_branch, initial_cursor) or turns the assignment on or off
    (enabled), which needs the project locked and drained, or revokes and re-grants it
    (revoked), which is admin only and takes effect at once.
    """
    assignment = _assignment(project_id, assignment_id)
    body = request.json or {}
    fields = {"watch_dir", "base_branch", "initial_cursor", "enabled", "revoked"}
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

    if "initial_cursor" in body:
        try:
            assignment.initial_cursor = body["initial_cursor"]
        except ValueError as e:
            raise InvalidRequest(str(e))
        # The timestamp itself is in scope
        assignment.initial_cursor_number = 0

    session.flush()
    _check_loop(assignment)
    session.commit()
    # An assignment that is active now has to catch up on what it missed: after it was
    # enabled or un-revoked, or when its cursor moved earlier
    if assignment.active and (not was_active or "initial_cursor" in body):
        backfill(assignment)
        session.commit()
    return ProjectTriggerRepositoryDTO.from_model(assignment).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project_trigger_repository(project_id: int, assignment_id: int):
    """
    DELETE /projects/<project_id>/trigger_repositories/<assignment_id> — removes the
    assignment, not the repository, once the project is locked and drained. Refused while it
    has pull requests.
    """
    assignment = _assignment(project_id, assignment_id)
    require_drained(assignment.project)
    try:
        assignment.delete()
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc
    return '', HTTPStatus.NO_CONTENT


def _pull_request(project_id: int, assignment_id: int, number: int) -> PullRequestTrigger:
    _assignment(project_id, assignment_id)
    pr = PullRequestTrigger.query.join(PullRequest).filter(
        PullRequestTrigger.project_trigger_repository_id == assignment_id,
        PullRequest.number == number
    ).one_or_none()
    if not pr:
        raise InvalidRequest(
            f"PR #{number} not found in trigger repository {assignment_id}", code=HTTPStatus.NOT_FOUND
        )
    return pr


def _ingest(assignment: ProjectTriggerRepository, bodies: list) -> list[PullRequestTrigger]:
    """
    Stores the pull requests on the assignment's repository and fans them out to every active
    assignment of it, and returns the assignment's own triggers for them, in the order given.
    Stays until the ingest posts once per repository (stage 7).
    """
    requests = [PullRequestRequest.parse(body) for body in bodies]
    ingest_pull_requests(assignment.trigger_repository_id, requests)
    session.commit()
    triggers = {
        pr.number: pr for pr in PullRequestTrigger.query.join(PullRequest).filter(
            PullRequestTrigger.project_trigger_repository_id == assignment.id,
            PullRequest.number.in_([r.number for r in requests]),
        )
    }
    return [triggers[r.number] for r in requests if r.number in triggers]


# TODO: the pull_requests routes below are called by Dagster only. No user or admin is
# expected to touch them, so they should be restricted to internal callers.
@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>/pull_requests', methods=['POST'])
@auth(scope='can_admin_dataset')
def post_pull_request(project_id: int, assignment_id: int):
    """
    POST /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests — ingest a
    pull request: store it on the repository and fan it out. Returns the assignment's trigger.
    Body: a pull request, see PullRequestRequest.
    """
    assignment = _assignment(project_id, assignment_id)
    triggers = _ingest(assignment, [request.json])
    if not triggers:
        raise InvalidRequest("The pull request is before the assignment's cursor, it has no trigger here")
    return PullRequestTriggerDTO.from_model(triggers[0]).dump(), HTTPStatus.CREATED


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>/pull_requests/batch', methods=['POST'])
@auth(scope='can_admin_dataset')
def post_pull_requests_batch(project_id: int, assignment_id: int):
    """
    POST /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/batch —
    ingest up to 100 pull requests: store them on the repository and fan them out. Posting
    known pull requests again changes nothing. Returns the assignment's triggers for them.
    Body: {"pull_requests": [pull requests, see PullRequestRequest]}
    """
    assignment = _assignment(project_id, assignment_id)

    body = (request.json or {}).get('pull_requests')

    if not isinstance(body, list):
        raise InvalidRequest("pull_requests must be a list of pull requests")

    if len(body) > 100:
        raise InvalidRequest("Maximum 100 pull requests per batch")

    triggers = _ingest(assignment, body)
    return [PullRequestTriggerDTO.from_model(pr).dump() for pr in triggers], HTTPStatus.CREATED


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>/pull_requests', methods=['GET'])
@auth(scope='can_admin_dataset')
def get_pull_requests(project_id: int, assignment_id: int):
    """
    GET /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests — list PRs
    of an assignment with pagination.
    Query params:
        - page: page number (default 1)
        - per_page: items per page (default 20)
        - state: filter by state (optional), one of: UNKNOWN, IGNORED, REJECTED, YIELDED
    Sorted by merged_at DESC (most recent first).
    """
    _assignment(project_id, assignment_id)

    page = arg_get('page', 1, type=int)
    per_page = arg_get('per_page', 20, type=int)
    state = request.args.get('state', None)

    query = PullRequestTrigger.query.join(PullRequest).filter(
        PullRequestTrigger.project_trigger_repository_id == assignment_id
    )

    if state is not None:
        if state not in [s.value for s in TriggerState]:
            valid = ', '.join([s.value for s in TriggerState])
            raise InvalidRequest(f"Invalid state: {state}. Must be one of: {valid}")
        query = query.filter(PullRequestTrigger.state == state)

    query = query.order_by(PullRequest.merged_at.desc(), PullRequest.number.desc())
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [PullRequestTriggerDTO.from_model(pr).dump() for pr in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
    }, HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>/pull_requests/<int:number>', methods=['GET'])
@auth(scope='can_admin_dataset')
def get_pull_request(project_id: int, assignment_id: int, number: int):
    """
    GET /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/<number> — get a single PR
    """
    pr = _pull_request(project_id, assignment_id, number)
    return PullRequestTriggerDTO.from_model(pr).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>/pull_requests/<int:number>', methods=['PATCH'])
@auth(scope='can_admin_dataset')
def patch_pull_request(project_id: int, assignment_id: int, number: int):
    """
    PATCH /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/<number> —
    update PR state and state_cause
    """
    pr = _pull_request(project_id, assignment_id, number)

    body = request.json or {}

    if 'state' in body or 'state_cause' in body:
        pr.set_state(body.get('state', pr.state), body.get('state_cause'))

    session.commit()
    return PullRequestTriggerDTO.from_model(pr).dump(), HTTPStatus.OK


@bp.route(f'{ASSIGNMENT_URL}/<int:assignment_id>/pull_requests/<int:number>/task', methods=['POST'])
@auth(scope='can_admin_dataset')
def post_task(project_id: int, assignment_id: int, number: int):
    """
    POST /projects/<project_id>/trigger_repositories/<assignment_id>/pull_requests/<number>/task
    — validate the pull request's spec and, in one transaction, mark it YIELDED and create its
    task. The project comes from the assignment.
    Body: {"spec_raw": "..."}, the pull request's spec file as read. It is kept on the pull
    request before it is parsed, so a rejected pull request keeps it too.
    Idempotent: if the pull request already has a task it is returned with a 200.
    """
    pr = _pull_request(project_id, assignment_id, number)

    if pr.task:
        return TaskDTO.from_model(pr.task).dump(), HTTPStatus.OK

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
