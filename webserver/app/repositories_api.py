"""
repositories-related endpoints (used by dagster for polling state):
- GET /repositories
- GET /repositories/<id>
- POST /repositories
- PATCH /repositories/<id>
- GET /repositories/<repo_id>/pull_requests
- GET /repositories/<repo_id>/pull_requests/<number>
- PATCH /repositories/<repo_id>/pull_requests/<number>
"""
from datetime import datetime
from http import HTTPStatus
from flask import Blueprint, request
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.wrappers import audit, auth
from app.models.repository import Repository
from app.models.pull_request import PullRequest
from app.models.pull_request_status import PullRequestStatus

bp = Blueprint('repositories', __name__, url_prefix='/repositories')
session = db.session


# TODO: re-enable auth
@bp.before_request
# @audit
# @auth(scope='can_do_admin')
def auth_and_admin_before():
    """
    Ensure the user is authenticated and has admin privileges before processing requests.
    """


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_repositories():
    """
    GET /repositories/ — list all repositories with their polling state
    """
    repos = Repository.query.all()
    return [r.sanitized_dict() for r in repos], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['DELETE'])
def delete_repository(repo_id):
    """
    DELETE /repositories/<id> — delete a single repository
    """
    repo = Repository.get_by_id(repo_id)
    repo.delete()
    return '', HTTPStatus.NO_CONTENT


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
def post_repository():
    """
    POST /repositories/ — create a new repository
    """
    body = request.json or {}
    if not body.get('uri') and body.get('watch_dir'):
        raise InvalidRequest("uri is required")

    uri = body['uri'].lower().rstrip('/')
    if Repository.query.filter(Repository.uri == uri).one_or_none():
        raise InvalidRequest(f"Repository {uri} already exists")

    repo = Repository(
        uri=uri,
        watch_dir=body['watch_dir'],
        base_branch=body.get('base_branch', 'main'),
    )
    repo.add()

    return repo.sanitized_dict(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
def patch_repository(repo_id):
    """
    PATCH /repositories/<id> — update pr_cursor and/or base_branch
    """
    repo = Repository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    if 'base_branch' in body:
        if not body['base_branch']:
            raise InvalidRequest("base_branch cannot be empty")
        repo.base_branch = body['base_branch']

    if 'watch_dir' in body:
        if not body['watch_dir']:
            raise InvalidRequest("watch_dir cannot be empty")
        repo.watch_dir = body['watch_dir']

    if 'polled_at' in body:
        try:
            repo.polled_at = datetime.fromisoformat(body['polled_at'])  # type: ignore[assignment]
        except (ValueError, TypeError):
            raise InvalidRequest("polled_at must be a valid ISO 8601 datetime string")

    session.commit()
    return repo.sanitized_dict(), HTTPStatus.OK


@bp.route('/pull_requests', methods=['POST'])
def post_pull_request():
    """
    POST /repositories/pull_requests — create a new pull request
    """
    body = request.json or {}

    # Validate required fields
    required = ['repository_id', 'number', 'title', 'raised_by', 'merged_at', 'merge_commit_sha', 'spec', 'is_valid']
    missing = [f for f in required if f not in body]
    if missing:
        raise InvalidRequest(f"Missing required fields: {', '.join(missing)}")

    # Parse merged_at if it's a string
    merged_at = body['merged_at']
    if isinstance(merged_at, str):
        try:
            merged_at = datetime.fromisoformat(merged_at.rstrip('Z'))
        except (ValueError, TypeError):
            raise InvalidRequest("merged_at must be a valid ISO 8601 datetime string")

    # Create PR
    status = body.get('status', PullRequestStatus.UNPROCESSED.value)
    pr = PullRequest(
        repository_id=body['repository_id'],
        number=body['number'],
        title=body['title'],
        raised_by=body['raised_by'],
        merged_at=merged_at,
        merge_commit_sha=body['merge_commit_sha'],
        spec=body.get('spec', {}),
        is_valid=body.get('is_valid', False),
        status=status,
    )
    pr.add()

    return _pr_to_dict(pr), HTTPStatus.CREATED


@bp.route('/<int:repo_id>/pull_requests/batch', methods=['POST'])
def post_pull_requests_batch(repo_id):
    """
    POST /repositories/<repo_id>/pull_requests/batch — create multiple pull requests for a repo
    Body: list of PR objects (up to 100)
    """
    Repository.get_by_id(repo_id)  # Verify repo exists

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
            required = ['number', 'title', 'raised_by', 'merged_at', 'merge_commit_sha', 'spec', 'is_valid']
            missing = [f for f in required if f not in pr_data]
            if missing:
                raise InvalidRequest(f"Missing required fields in PR: {', '.join(missing)}")

            # Validate status if provided
            if 'status' in pr_data:
                if pr_data['status'] not in [s.value for s in PullRequestStatus]:
                    raise InvalidRequest(f"Invalid status: {pr_data['status']}")

            # Parse merged_at if it's a string
            merged_at = pr_data['merged_at']
            if isinstance(merged_at, str):
                try:
                    merged_at = datetime.fromisoformat(merged_at.rstrip('Z'))
                except (ValueError, TypeError):
                    raise InvalidRequest("merged_at must be a valid ISO 8601 datetime string")

            # Create PR (repository_id always from URL)
            status = pr_data.get('status', PullRequestStatus.UNPROCESSED.value)
            pr = PullRequest(
                repository_id=repo_id,
                number=pr_data['number'],
                title=pr_data['title'],
                raised_by=pr_data['raised_by'],
                merged_at=merged_at,
                merge_commit_sha=pr_data['merge_commit_sha'],
                spec=pr_data.get('spec', {}),
                is_valid=pr_data.get('is_valid', False),
                status=status,
            )
            pr.add(commit=False)  # Don't commit yet, batch commit at end
            created_prs.append(pr)
        except Exception as e:
            session.rollback()
            raise InvalidRequest(f"Error creating PR #{pr_data.get('number', '?')}: {str(e)}")

    # Batch commit all PRs
    session.commit()

    return [_pr_to_dict(pr) for pr in created_prs], HTTPStatus.CREATED


@bp.route('/<int:repo_id>/pull_requests', methods=['GET'])
def get_pull_requests(repo_id):
    """
    GET /repositories/<repo_id>/pull_requests — list PRs for a repository with pagination.
    Query params:
      - page: page number (default 1)
      - per_page: items per page (default 20)
      - status: filter by status (optional, one of: unprocessed, in_progress, success, failed)
      - is_valid: filter by validity (optional, 'true'/'false')
    Sorted by merged_at DESC (most recent first).
    """
    Repository.get_by_id(repo_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', None)
    is_valid = request.args.get('is_valid', None)

    query = PullRequest.query.filter(PullRequest.repository_id == repo_id)

    if status is not None:
        if status not in [s.value for s in PullRequestStatus]:
            raise InvalidRequest(f"Invalid status: {status}. Must be one of: {', '.join([s.value for s in PullRequestStatus])}")
        query = query.filter(PullRequest.status == status)

    if is_valid is not None:
        is_valid_bool = is_valid.lower() == 'true'
        query = query.filter(PullRequest.is_valid == is_valid_bool)

    query = query.order_by(PullRequest.merged_at.desc())
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [_pr_to_dict(pr) for pr in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
    }, HTTPStatus.OK


@bp.route('/<int:repo_id>/pull_requests/<int:number>', methods=['GET'])
def get_pull_request(repo_id, number):
    """
    GET /repositories/<repo_id>/pull_requests/<number> — get a single PR
    """
    Repository.get_by_id(repo_id)
    pr = PullRequest.query.filter(
        PullRequest.repository_id == repo_id,
        PullRequest.number == number
    ).one_or_none()

    if not pr:
        raise InvalidRequest(f"PR #{number} not found in repository {repo_id}", code=HTTPStatus.NOT_FOUND)

    return _pr_to_dict(pr), HTTPStatus.OK


@bp.route('/<int:repo_id>/pull_requests/<int:number>', methods=['PATCH'])
def patch_pull_request(repo_id, number):
    """
    PATCH /repositories/<repo_id>/pull_requests/<number> — update PR status
    """
    Repository.get_by_id(repo_id)
    pr = PullRequest.query.filter(
        PullRequest.repository_id == repo_id,
        PullRequest.number == number
    ).one_or_none()

    if not pr:
        raise InvalidRequest(f"PR #{number} not found in repository {repo_id}", code=HTTPStatus.NOT_FOUND)

    body = request.json or {}
    if 'status' in body:
        status_value = body['status']
        if status_value not in [s.value for s in PullRequestStatus]:
            raise InvalidRequest(f"Invalid status: {status_value}. Must be one of: {', '.join([s.value for s in PullRequestStatus])}")
        pr.status = status_value

    session.commit()
    return _pr_to_dict(pr), HTTPStatus.OK


def _pr_to_dict(pr: PullRequest) -> dict:
    """Convert PR to dict for serialization"""
    return {
        'repository_id': pr.repository_id,
        'number': pr.number,
        'title': pr.title,
        'raised_by': pr.raised_by,
        'merge_commit_sha': pr.merge_commit_sha,
        'merged_at': pr.merged_at.isoformat() if pr.merged_at else None,
        'saved_at': pr.saved_at.isoformat() if pr.saved_at else None,
        'is_valid': pr.is_valid,
        'status': pr.status,
        'spec': pr.spec,
    }
