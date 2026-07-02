"""
repositories-related endpoints (used by dagster for polling state):
- GET /repositories
- GET /repositories/<id>
- POST /repositories
- PATCH /repositories/<id>
"""
from datetime import datetime
from http import HTTPStatus
from flask import Blueprint, request
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.wrappers import audit, auth
from app.models.repository import Repository

bp = Blueprint('repositories', __name__, url_prefix='/repositories')
session = db.session


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_do_admin')
def get_repositories():
    """
    GET /repositories/ — list all repositories with their polling state
    """
    repos = Repository.query.all()
    return [r.sanitized_dict() for r in repos], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['GET'])
@audit
@auth(scope='can_do_admin')
def get_repository(repo_id):
    """
    GET /repositories/<id> — get a single repository
    """
    repo = Repository.get_by_id(repo_id)
    return repo.sanitized_dict(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_do_admin')
def post_repository():
    """
    POST /repositories/ — create a new repository
    """
    body = request.json or {}
    if not body.get('uri'):
        raise InvalidRequest("uri is required")

    uri = body['uri'].lower().rstrip('/')
    if Repository.query.filter(Repository.uri == uri).one_or_none():
        raise InvalidRequest(f"Repository {uri} already exists")

    repo = Repository(uri=uri, base_branch=body.get('base_branch', 'main'))
    repo.add()
    return repo.sanitized_dict(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
@audit
@auth(scope='can_do_admin')
def patch_repository(repo_id):
    """
    PATCH /repositories/<id> — update pr_cursor and/or base_branch
    """
    repo = Repository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    if 'pr_cursor' in body:
        last_pr = body['pr_cursor']
        if not isinstance(last_pr, int) or last_pr < 0:
            raise InvalidRequest("pr_cursor must be a non-negative integer")
        repo.pr_cursor = last_pr

    if 'base_branch' in body:
        if not body['base_branch']:
            raise InvalidRequest("base_branch cannot be empty")
        repo.base_branch = body['base_branch']

    if 'polled_at' in body:
        try:
            repo.polled_at = datetime.fromisoformat(body['polled_at']) # type: ignore[assignment]
        except (ValueError, TypeError):
            raise InvalidRequest("polled_at must be a valid ISO 8601 datetime string")

    session.commit()
    return repo.sanitized_dict(), HTTPStatus.OK
