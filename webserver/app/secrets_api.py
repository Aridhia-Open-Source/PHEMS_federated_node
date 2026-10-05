"""
Secret endpoints. The values only ever go to the secret store; the database keeps a
reference so that repositories can share a secret. A secret belongs to a project and is
addressed by its label within it:
- GET /projects/<project_id>/secrets
- GET /projects/<project_id>/secrets/<label>
- POST /projects/<project_id>/secrets
- PATCH /projects/<project_id>/secrets/<label>
- DELETE /projects/<project_id>/secrets/<label>
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
from app.models.secret_provider_name import SecretProviderName

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


class K8sSecretProvider:
    """Writes and deletes secrets in Kubernetes."""

    def set(self, key: str, values: dict[str, str]):
        """The caller is the authority on the content, so it overwrites what is there."""
        KubernetesClient().create_secret(
            name=key,
            values=values,
            namespaces=[DEFAULT_NAMESPACE],
            labels=SECRET_LABELS,
            overwrite=True,
        )

    def delete(self, key: str):
        try:
            KubernetesClient().delete_namespaced_secret(key, DEFAULT_NAMESPACE)
        except ApiException as apie:
            if apie.status != 404:
                logger.error(apie)
                raise InvalidRequest("Could not clear the secret properly") from apie


class SecretProvider:
    """Writes and deletes secret values in the store the provider name selects."""

    PROVIDERS = {SecretProviderName.K8S: K8sSecretProvider}

    def __init__(self, name: SecretProviderName):
        self.provider = self.PROVIDERS[name]()

    def set(self, key: str, values: dict[str, str]):
        self.provider.set(key, values)

    def delete(self, key: str):
        self.provider.delete(key)


def _get_secret(project_id: int, label: str) -> Secret:
    Project.get_by_id(project_id)
    secret = Secret.query.filter(Secret.project_id == project_id, Secret.label == label).one_or_none()
    if not secret:
        raise DBRecordNotFoundError(f"Secret {label} does not exist in project {project_id}")
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


@bp.route('/<label>', methods=['GET'])
def get_secret(project_id, label):
    """
    GET /projects/<project_id>/secrets/<label> — get a single secret.
    The values are never returned.
    """
    return SecretDTO.from_model(_get_secret(project_id, label)).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
def post_secret(project_id):
    """
    POST /projects/<project_id>/secrets — create the secret in its store and the reference
    to it. The label is the project-local name; the secret is stored under the generated
    key "<project_id>-<label>", which is fixed from then on.
    Body: {"label": "...", "description": "...", "provider": "K8S", "values": {"KEY": "value", ...}}
    The description is optional.
    """
    body = request.json or {}
    if not body.get('label'):
        raise InvalidRequest("label is required")
    try:
        provider = SecretProviderName(body.get('provider'))
    except ValueError:
        raise InvalidRequest(f"provider must be one of {[t.value for t in SecretProviderName]}")
    values = _get_values(body)

    Project.get_by_id(project_id)
    if Secret.query.filter(Secret.project_id == project_id, Secret.label == body['label']).one_or_none():
        raise InvalidRequest(f"Secret {body['label']} already exists", code=HTTPStatus.CONFLICT)

    try:
        secret = Secret(
            project_id=project_id,
            label=body['label'],
            provider=provider,
            description=body.get('description'),
        )
    except ValueError as e:
        raise InvalidRequest(str(e))

    # The store first, so a failure there leaves no row pointing at nothing. If the row
    # then fails, the stored secret is left for a retry to adopt: writing it overwrites.
    SecretProvider(secret.provider).set(secret.key, values)
    secret.add()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.CREATED


@bp.route('/<label>', methods=['PATCH'])
@audit
def patch_secret(project_id, label):
    """
    PATCH /projects/<project_id>/secrets/<label> — set keys on the stored secret, e.g. to
    rotate a token. Every repository that references it picks the new values up.
    Body: {"values": {"KEY": "value", ...}}
    """
    secret = _get_secret(project_id, label)
    values = _get_values(request.json or {})

    SecretProvider(secret.provider).set(secret.key, values)
    secret.updated_at = dt.now()
    session.commit()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.OK


@bp.route('/<label>', methods=['DELETE'])
@audit
def delete_secret(project_id, label):
    """
    DELETE /projects/<project_id>/secrets/<label> — delete the reference and the stored
    secret. Refused while a repository or dataset still uses it.
    """
    secret = _get_secret(project_id, label)
    users = len(secret.trigger_repositories) + len(secret.results_repositories) + len(secret.datasets)
    if users:
        raise InvalidRequest(
            f"Secret {secret.label} is still used by {users} repositories or datasets",
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
        SecretProvider(secret.provider).delete(secret.key)
    except InvalidRequest:
        session.rollback()
        raise

    session.commit()
    return '', HTTPStatus.NO_CONTENT
