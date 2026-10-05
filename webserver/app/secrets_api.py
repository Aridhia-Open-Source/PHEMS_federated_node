"""
Secret endpoints. The values only ever go to the secret store; the database keeps a
reference so that repositories can share a secret. A secret belongs to a project and is
addressed by its name within it:
- GET /projects/<project_id>/secrets
- GET /projects/<project_id>/secrets/<name>
- POST /projects/<project_id>/secrets
- PATCH /projects/<project_id>/secrets/<name>
- DELETE /projects/<project_id>/secrets/<name>
"""
import logging
import re
from datetime import datetime as dt
from http import HTTPStatus

from flask import Blueprint, request
from kubernetes.client.exceptions import ApiException

from app.dtos.secret import SecretDTO
from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.kubernetes import KubernetesClient
from app.helpers.wrappers import audit, auth
from app.models.project import Project
from app.models.secret import Secret
from app.models.secret_type import SecretType

logger = logging.getLogger('secrets_api')
bp = Blueprint('secrets', __name__, url_prefix='/projects/<int:project_id>/secrets')
session = db.session

SECRET_LABELS = {"type": "k8s_secret"}
SECRET_KEY = re.compile(r'[-._a-zA-Z0-9]+')


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


def _get_values(body: dict) -> dict[str, str]:
    values = body.get('values')
    if not isinstance(values, dict) or not values:
        raise InvalidRequest("values is required and must be a non-empty object")
    for key, value in values.items():
        if not SECRET_KEY.fullmatch(key):
            raise InvalidRequest(f"Invalid key {key!r}: use letters, digits, '-', '_' or '.'")
        if not isinstance(value, str) or not value:
            raise InvalidRequest(f"The value for {key} must be a non-empty string")
    # create_secret encodes the values in place, so it gets a copy
    return dict(values)


def _write_k8s_secret(store_name: str, values: dict[str, str]):
    """The caller is the authority on the content, so it overwrites what is there."""
    KubernetesClient().create_secret(
        name=store_name,
        values=values,
        namespaces=[DEFAULT_NAMESPACE],
        labels=SECRET_LABELS,
        overwrite=True,
    )


def _delete_k8s_secret(store_name: str):
    try:
        KubernetesClient().delete_namespaced_secret(store_name, DEFAULT_NAMESPACE)
    except ApiException as apie:
        if apie.status != 404:
            logger.error(apie)
            raise InvalidRequest("Could not clear the secret properly") from apie


# What to call to write or delete a secret's value, by the store it lives in.
WRITE_VALUES = {SecretType.K8S: _write_k8s_secret}
DELETE_VALUES = {SecretType.K8S: _delete_k8s_secret}


def _get_secret(project_id: int, name: str) -> Secret:
    Project.get_by_id(project_id)
    secret = Secret.query.filter(Secret.project_id == project_id, Secret.name == name).one_or_none()
    if not secret:
        raise DBRecordNotFoundError(f"Secret {name} does not exist in project {project_id}")
    return secret


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_secrets(project_id):
    """
    GET /projects/<project_id>/secrets — list the project's secrets.
    The values are never returned.
    """
    Project.get_by_id(project_id)
    secrets = Secret.query.filter(Secret.project_id == project_id).all()
    return [SecretDTO.from_model(s).dump() for s in secrets], HTTPStatus.OK


@bp.route('/<name>', methods=['GET'])
def get_secret(project_id, name):
    """
    GET /projects/<project_id>/secrets/<name> — get a single secret.
    The values are never returned.
    """
    return SecretDTO.from_model(_get_secret(project_id, name)).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
def post_secret(project_id):
    """
    POST /projects/<project_id>/secrets — create the secret in its store and the reference
    to it. In a Kubernetes store the secret is named "<project_id>-<name>".
    Body: {"name": "...", "secret_type": "K8S", "values": {"KEY": "value", ...}}
    """
    body = request.json or {}
    if not body.get('name'):
        raise InvalidRequest("name is required")
    try:
        secret_type = SecretType(body.get('secret_type'))
    except ValueError:
        raise InvalidRequest(f"secret_type must be one of {[t.value for t in SecretType]}")
    values = _get_values(body)

    Project.get_by_id(project_id)
    if Secret.query.filter(Secret.project_id == project_id, Secret.name == body['name']).one_or_none():
        raise InvalidRequest(f"Secret {body['name']} already exists", code=HTTPStatus.CONFLICT)

    try:
        secret = Secret(project_id=project_id, name=body['name'], secret_type=secret_type)
    except ValueError as e:
        raise InvalidRequest(str(e))

    # The store first, so a failure there leaves no row pointing at nothing. If the row
    # then fails, the stored secret is left for a retry to adopt: writing it overwrites.
    WRITE_VALUES[secret.secret_type](secret.store_name, values)
    secret.add()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.CREATED


@bp.route('/<name>', methods=['PATCH'])
@audit
def patch_secret(project_id, name):
    """
    PATCH /projects/<project_id>/secrets/<name> — set keys on the stored secret, e.g. to
    rotate a token. Every repository that references it picks the new values up. The name
    cannot change.
    Body: {"values": {"KEY": "value", ...}}
    """
    secret = _get_secret(project_id, name)
    values = _get_values(request.json or {})

    WRITE_VALUES[secret.secret_type](secret.store_name, values)
    secret.updated_at = dt.now()
    session.commit()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.OK


@bp.route('/<name>', methods=['DELETE'])
@audit
def delete_secret(project_id, name):
    """
    DELETE /projects/<project_id>/secrets/<name> — delete the reference and the stored
    secret. Refused while a repository or dataset still uses it.
    """
    secret = _get_secret(project_id, name)
    users = len(secret.trigger_repositories) + len(secret.datasets)
    if users:
        raise InvalidRequest(
            f"Secret {secret.name} is still used by {users} repositories or datasets",
            code=HTTPStatus.CONFLICT
        )

    # Staged, not committed: if the store delete fails the row has to come back, and a
    # rollback after a commit is a no-op.
    try:
        secret.delete(False)
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc

    try:
        DELETE_VALUES[secret.secret_type](secret.store_name)
    except InvalidRequest:
        session.rollback()
        raise

    session.commit()
    return '', HTTPStatus.NO_CONTENT
