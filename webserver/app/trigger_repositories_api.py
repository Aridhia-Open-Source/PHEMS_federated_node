"""
trigger repository endpoints (used by dagster for polling state):
- GET /trigger_repositories
- GET /trigger_repositories/<id>
- POST /trigger_repositories
- PATCH /trigger_repositories/<id>
- DELETE /trigger_repositories/<id>
- POST /trigger_repositories/pull_requests
- POST /trigger_repositories/<repo_id>/pull_requests/batch
- GET /trigger_repositories/<repo_id>/pull_requests
- GET /trigger_repositories/<repo_id>/pull_requests/<number>
- PATCH /trigger_repositories/<repo_id>/pull_requests/<number>
- POST /trigger_repositories/<repo_id>/pull_requests/<number>/task
"""
from http import HTTPStatus

from flask import Blueprint, request
from sqlalchemy.exc import IntegrityError

from app.dtos.task import NewTaskDTO, TaskDTO
from app.dtos.trigger_repository import PullRequestDTO, TriggerRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.dtos.task_spec import TaskSpec
from app.helpers.wrappers import auth
from app.models.k8s_secret import K8sSecret
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.task import Task
from app.models.trigger_repository import TriggerRepository
from app.models.trigger_state import TriggerState

# TODO: the pull_requests routes below are called by Dagster only. No user or admin is
# expected to touch them, so they should be restricted to internal callers.
bp = Blueprint('trigger_repositories', __name__, url_prefix='/trigger_repositories')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_repositories():
    """
    GET /trigger_repositories/ — list all repositories with their polling state
    """
    repos = TriggerRepository.query.all()
    return [TriggerRepositoryDTO.from_model(r).dump() for r in repos], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['GET'])
def get_repository(repo_id):
    """
    GET /trigger_repositories/<id> — get a single repository
    """
    repo = TriggerRepository.get_by_id(repo_id)
    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['DELETE'])
def delete_repository(repo_id):
    """
    DELETE /trigger_repositories/<id> — delete a single repository
    """
    repo = TriggerRepository.get_by_id(repo_id)
    repo.delete()
    return '', HTTPStatus.NO_CONTENT


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
def post_repository():
    """
    POST /trigger_repositories/ — create a new repository
    """
    body = request.json or {}
    if not body.get('uri'):
        raise InvalidRequest("uri is required")
    if not body.get('project_id'):
        raise InvalidRequest("project_id is required")
    for field in ('provider', 'api_uri', 'k8s_secret_name'):
        if not body.get(field):
            raise InvalidRequest(f"{field} is required")

    uri = TriggerRepository.parse_repo_uri(body['uri'])
    if TriggerRepository.query.filter_by(project_id=body['project_id'], uri=uri).one_or_none():
        raise InvalidRequest(f"Repository {uri} already exists in project {body['project_id']}")

    # Validate project and secret exist
    Project.get_by_id(body['project_id'])
    secret = K8sSecret.get_in_project(body['project_id'], body['k8s_secret_name'])

    try:
        repo = TriggerRepository(
            uri=uri,
            provider=body['provider'],
            api_uri=body['api_uri'],
            k8s_secret_id=secret.id,
            watch_dir=body.get('watch_dir', ''),
            project_id=body['project_id'],
            base_branch=body.get('base_branch', 'main'),
            initial_cursor=body.get('initial_cursor'),
            repo_path=body.get('repo_path'),
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    repo.add()

    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
def patch_repository(repo_id):
    """
    PATCH /trigger_repositories/<id> — update repository
    """
    repo = TriggerRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    if 'project_id' in body:
        Project.get_by_id(body['project_id'])
        repo.project_id = body['project_id']

    if 'base_branch' in body:
        if not body['base_branch']:
            raise InvalidRequest("base_branch cannot be empty")
        repo.base_branch = body['base_branch']

    if 'watch_dir' in body:
        if not body['watch_dir']:
            raise InvalidRequest("watch_dir cannot be empty")
        repo.watch_dir = body['watch_dir']

    if 'k8s_secret_name' in body:
        if not body['k8s_secret_name']:
            raise InvalidRequest("k8s_secret_name cannot be empty")
        repo.k8s_secret_id = K8sSecret.get_in_project(repo.project_id, body['k8s_secret_name']).id

    for field in ('provider', 'api_uri'):
        if field in body:
            if not body[field]:
                raise InvalidRequest(f"{field} cannot be empty")
            try:
                setattr(repo, field, body[field])
            except ValueError as e:
                raise InvalidRequest(str(e))

    if 'initial_cursor' in body:
        repo.initial_cursor = body['initial_cursor']

    session.commit()
    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK


# TODO: internal, called by Dagster only. Restrict to internal callers.
@bp.route('/pull_requests', methods=['POST'])
def post_pull_request():
    """
    POST /trigger_repositories/pull_requests — create a new pull request
    """
    body = request.json or {}
    required = ['trigger_repository_id', 'number', 'title', 'raised_by', 'merged_at', 'merge_commit_sha', 'payload']
    missing = [f for f in required if f not in body]
    if missing:
        raise InvalidRequest(f"Missing required fields: {', '.join(missing)}")

    # Create PR
    repo = TriggerRepository.get_by_id(body['trigger_repository_id'])
    pr = PullRequest(
        project_id=repo.project_id,
        trigger_repository_id=body['trigger_repository_id'],
        number=body['number'],
        title=body['title'],
        raised_by=body['raised_by'],
        merged_at=body['merged_at'],
        merge_commit_sha=body['merge_commit_sha'],
        payload=body.get('payload', {}),
    )
    pr.add()

    return PullRequestDTO.from_model(pr).dump(), HTTPStatus.CREATED


# TODO: internal, called by Dagster only. Restrict to internal callers.
@bp.route('/<int:repo_id>/pull_requests/batch', methods=['POST'])
def post_pull_requests_batch(repo_id):
    """
    POST /trigger_repositories/<repo_id>/pull_requests/batch — create multiple pull requests for a repo
    Body: list of PR objects (up to 100)
    """
    repo = TriggerRepository.get_by_id(repo_id)  # Verify repo exists

    body = request.json or []

    if not isinstance(body, list):
        raise InvalidRequest("Body must be a list of pull requests")

    if len(body) > 100:
        raise InvalidRequest("Maximum 100 pull requests per batch")

    if not body:
        return [], HTTPStatus.CREATED

    created_prs = []
    for pr_data in body:
        try:
            # Validate required fields
            required = ['number', 'title', 'raised_by', 'merged_at', 'merge_commit_sha', 'payload']
            missing = [f for f in required if f not in pr_data]
            if missing:
                raise InvalidRequest(f"Missing required fields in PR: {', '.join(missing)}")

            # Create PR (repository_id always from URL)
            pr = PullRequest(
                project_id=repo.project_id,
                trigger_repository_id=repo_id,
                number=pr_data['number'],
                title=pr_data['title'],
                raised_by=pr_data['raised_by'],
                merged_at=pr_data['merged_at'],
                merge_commit_sha=pr_data['merge_commit_sha'],
                payload=pr_data.get('payload', {}),
            )
            pr.add(commit=False)  # Don't commit yet, batch commit at end
            created_prs.append(pr)
        except Exception as e:
            session.rollback()
            raise InvalidRequest(f"Error creating PR #{pr_data.get('number', '?')}: {str(e)}")

    # Batch commit all PRs
    session.commit()

    return [PullRequestDTO.from_model(pr).dump() for pr in created_prs], HTTPStatus.CREATED


# TODO: internal, called by Dagster only. Restrict to internal callers.
@bp.route('/<int:repo_id>/pull_requests', methods=['GET'])
def get_pull_requests(repo_id):
    """
    GET /trigger_repositories/<repo_id>/pull_requests — list PRs for a repository with pagination.
    Query params:
        - page: page number (default 1)
        - per_page: items per page (default 20)
        - state: filter by state (optional), one of: UNKNOWN, IGNORED, REJECTED, YIELDED
    Sorted by merged_at DESC (most recent first).
    """
    TriggerRepository.get_by_id(repo_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    state = request.args.get('state', None)

    query = PullRequest.query.filter(PullRequest.trigger_repository_id == repo_id)

    if state is not None:
        if state not in [s.value for s in TriggerState]:
            valid = ', '.join([s.value for s in TriggerState])
            raise InvalidRequest(f"Invalid state: {state}. Must be one of: {valid}")
        query = query.filter(PullRequest.state == state)

    query = query.order_by(PullRequest.merged_at.desc())
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [PullRequestDTO.from_model(pr).dump() for pr in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
    }, HTTPStatus.OK


# TODO: internal, called by Dagster only. Restrict to internal callers.
@bp.route('/<int:repo_id>/pull_requests/<int:number>', methods=['GET'])
def get_pull_request(repo_id, number):
    """
    GET /trigger_repositories/<repo_id>/pull_requests/<number> — get a single PR
    """
    TriggerRepository.get_by_id(repo_id)
    pr = PullRequest.query.filter(
        PullRequest.trigger_repository_id == repo_id,
        PullRequest.number == number
    ).one_or_none()

    if not pr:
        raise InvalidRequest(f"PR #{number} not found in repository {repo_id}", code=HTTPStatus.NOT_FOUND)

    return PullRequestDTO.from_model(pr).dump(), HTTPStatus.OK


# TODO: internal, called by Dagster only. Restrict to internal callers.
@bp.route('/<int:repo_id>/pull_requests/<int:number>', methods=['PATCH'])
def patch_pull_request(repo_id, number):
    """
    PATCH /trigger_repositories/<repo_id>/pull_requests/<number> — update PR state, state_cause and payload
    """
    TriggerRepository.get_by_id(repo_id)
    pr = PullRequest.query.filter(
        PullRequest.trigger_repository_id == repo_id,
        PullRequest.number == number
    ).one_or_none()

    if not pr:
        raise InvalidRequest(f"PR #{number} not found in repository {repo_id}", code=HTTPStatus.NOT_FOUND)

    body = request.json or {}

    if 'state' in body or 'state_cause' in body:
        pr.set_state(body.get('state', pr.state), body.get('state_cause'))

    if 'payload' in body:
        pr.payload = body['payload']

    session.commit()
    return PullRequestDTO.from_model(pr).dump(), HTTPStatus.OK


# TODO: internal, called by Dagster only. Restrict to internal callers.
@bp.route('/<int:repo_id>/pull_requests/<int:number>/task', methods=['POST'])
def post_task(repo_id, number):
    """
    POST /trigger_repositories/<repo_id>/pull_requests/<number>/task — validate the pull
    request's spec and, in one transaction, mark it YIELDED and create its task. The project
    comes from the repository.
    Body: {"payload": {...}}, the pull request's flat task spec.
    Idempotent: if the pull request already has a task it is returned with a 200.
    """
    TriggerRepository.get_by_id(repo_id)
    pr = PullRequest.query.filter(
        PullRequest.trigger_repository_id == repo_id,
        PullRequest.number == number
    ).one_or_none()

    if not pr:
        raise InvalidRequest(f"PR #{number} not found in repository {repo_id}", code=HTTPStatus.NOT_FOUND)

    if pr.task:
        return TaskDTO.from_model(pr.task).dump(), HTTPStatus.OK

    body = request.json or {}
    payload = body.get('payload')
    if not isinstance(payload, dict):
        raise InvalidRequest("payload is required and must be an object")

    spec = TaskSpec.from_pr_spec(payload)
    # A bad dataset override fails now, before anything is written
    new_task = NewTaskDTO.from_spec(spec, pr)

    pr.set_state(TriggerState.YIELDED.value, None)
    pr.payload = payload
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
