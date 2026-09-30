"""
k8s secret endpoints. The values only ever go to the cluster; the database keeps a
reference so that repositories can share a secret:
- GET /k8s_secrets
- GET /k8s_secrets/<id>
- POST /k8s_secrets
- PATCH /k8s_secrets/<id>
- DELETE /k8s_secrets/<id>
"""
import logging
import re
from datetime import datetime as dt
from http import HTTPStatus

from flask import Blueprint, request
from kubernetes.client.exceptions import ApiException

from app.dtos.k8s_secret import K8sSecretDTO
from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE
from app.helpers.exceptions import InvalidRequest
from app.helpers.kubernetes import KubernetesClient
from app.helpers.wrappers import audit, auth
from app.models.k8s_secret import K8sSecret

logger = logging.getLogger('k8s_secrets_api')
bp = Blueprint('k8s_secrets', __name__, url_prefix='/k8s_secrets')
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


def _write_cluster_secret(name: str, values: dict[str, str]):
    """The caller is the authority on the content, so it overwrites what is there."""
    KubernetesClient().create_secret(
        name=name,
        values=values,
        namespaces=[DEFAULT_NAMESPACE],
        labels=SECRET_LABELS,
        overwrite=True,
    )


def _delete_cluster_secret(name: str):
    try:
        KubernetesClient().delete_namespaced_secret(name, DEFAULT_NAMESPACE)
    except ApiException as apie:
        if apie.status != 404:
            logger.error(apie)
            raise InvalidRequest("Could not clear the secret properly") from apie


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_k8s_secrets():
    """
    GET /k8s_secrets — list the secrets. The values are never returned.
    """
    return [K8sSecretDTO.from_model(s).dump() for s in K8sSecret.query.all()], HTTPStatus.OK


@bp.route('/<int:secret_id>', methods=['GET'])
def get_k8s_secret(secret_id):
    """
    GET /k8s_secrets/<id> — get a single secret. The values are never returned.
    """
    return K8sSecretDTO.from_model(K8sSecret.get_by_id(secret_id)).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
def post_k8s_secret():
    """
    POST /k8s_secrets — create the cluster secret and the reference to it
    Body: {"name": "...", "values": {"KEY": "value", ...}}
    """
    body = request.json or {}
    if not body.get('name'):
        raise InvalidRequest("name is required")
    values = _get_values(body)

    if K8sSecret.query.filter(K8sSecret.name == body['name']).one_or_none():
        raise InvalidRequest(f"K8s secret {body['name']} already exists", code=HTTPStatus.CONFLICT)

    try:
        secret = K8sSecret(name=body['name'])
    except ValueError as e:
        raise InvalidRequest(str(e))

    # The cluster first, so a failure there leaves no row pointing at nothing. If the row
    # then fails, the cluster secret is left for a retry to adopt: writing it overwrites.
    _write_cluster_secret(secret.name, values)
    secret.add()

    return K8sSecretDTO.from_model(secret).dump(), HTTPStatus.CREATED


@bp.route('/<int:secret_id>', methods=['PATCH'])
@audit
def patch_k8s_secret(secret_id):
    """
    PATCH /k8s_secrets/<id> — set keys on the cluster secret, e.g. to rotate a token.
    Every repository that references it picks the new values up. The name cannot change.
    Body: {"values": {"KEY": "value", ...}}
    """
    secret = K8sSecret.get_by_id(secret_id)
    values = _get_values(request.json or {})

    _write_cluster_secret(secret.name, values)
    secret.updated_at = dt.now()
    session.commit()

    return K8sSecretDTO.from_model(secret).dump(), HTTPStatus.OK


@bp.route('/<int:secret_id>', methods=['DELETE'])
@audit
def delete_k8s_secret(secret_id):
    """
    DELETE /k8s_secrets/<id> — delete the reference and the cluster secret.
    Refused while a repository still uses it.
    """
    secret = K8sSecret.get_by_id(secret_id)
    users = len(secret.trigger_repositories) + len(secret.datasets)
    if users:
        raise InvalidRequest(
            f"K8s secret {secret.name} is still used by {users} repositories or datasets",
            code=HTTPStatus.CONFLICT
        )

    # Staged, not committed: if the cluster delete fails the row has to come back, and a
    # rollback after a commit is a no-op.
    try:
        secret.delete(False)
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc

    try:
        _delete_cluster_secret(secret.name)
    except InvalidRequest:
        session.rollback()
        raise

    session.commit()
    return '', HTTPStatus.NO_CONTENT
