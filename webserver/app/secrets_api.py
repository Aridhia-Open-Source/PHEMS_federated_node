"""
Secret endpoints. The values only ever go to the secret store; the database keeps a
reference so that repositories and datasets can share a secret. A secret belongs to no
project and is addressed by its label, which is unique. Creating and deleting are admin-only:
- GET /secrets
- GET /secrets/<label>
- POST /secrets
- PATCH /secrets/<label>
- DELETE /secrets/<label>
"""
import logging
from datetime import datetime as dt
from http import HTTPStatus

from flask import Blueprint, request
from kubernetes.client.exceptions import ApiException

from app.dtos.secret import SecretDTO
from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.kubernetes import KubernetesClient
from app.helpers.kubernetes_names import validate_secret_key
from app.helpers.wrappers import audit, auth
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType

logger = logging.getLogger('secrets_api')
bp = Blueprint('secrets', __name__, url_prefix='/secrets')
session = db.session

SECRET_LABELS = {"type": "k8s_secret"}


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""



def _get_values(body: dict) -> dict[str, str]:
    values = body.get('values')
    if not isinstance(values, dict) or not values:
        raise InvalidRequest("values is required and must be a non-empty object")
    for key, value in values.items():
        validate_secret_key(key, f"Key {key!r}")
        if not isinstance(value, str) or not value:
            raise InvalidRequest(f"The value for {key} must be a non-empty string")
    # create_secret encodes the values in place, so it gets a copy
    return dict(values)


class K8sSecretProvider:
    """Writes and deletes secrets in Kubernetes."""

    namespace = DEFAULT_NAMESPACE

    def set(self, key: str, namespace: str, values: dict[str, str]):
        """The caller is the authority on the content, so it overwrites what is there."""
        KubernetesClient().create_secret(
            name=key,
            values=values,
            namespaces=[namespace],
            labels=SECRET_LABELS,
            overwrite=True,
        )

    def delete(self, key: str, namespace: str):
        try:
            KubernetesClient().delete_namespaced_secret(key, namespace)
        except ApiException as apie:
            if apie.status != 404:
                logger.error(apie)
                raise InvalidRequest("Could not clear the secret properly") from apie


class SecretProvider:
    """Writes and deletes secret values in the store the provider name selects."""

    PROVIDERS = {SecretProviderType.K8S: K8sSecretProvider}

    def __init__(self, name: SecretProviderType):
        self.provider = self.PROVIDERS[name]()

    @property
    def namespace(self) -> str | None:
        return self.provider.namespace

    def set(self, key: str, namespace: str, values: dict[str, str]):
        self.provider.set(key, namespace, values)

    def delete(self, key: str, namespace: str):
        self.provider.delete(key, namespace)


def _get_secret(label: str) -> Secret:
    secret = Secret.query.filter(Secret.label == label).one_or_none()
    if not secret:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")
    return secret


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_secrets():
    """
    GET /secrets — list the secrets. The values are never returned.
    """
    return [SecretDTO.from_model(s).dump() for s in Secret.query.all()], HTTPStatus.OK


@bp.route('/<label>', methods=['GET'])
def get_secret(label):
    """
    GET /secrets/<label> — get a single secret. The values are never returned.
    """
    return SecretDTO.from_model(_get_secret(label)).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_do_admin', check_dataset=False)
def post_secret():
    """
    POST /secrets — create the secret in its store and the reference to it. The label is
    unique across the node; the secret is stored under the generated key
    "fn-secret-<label>", which is fixed from then on. Admin only.
    Body: {"label": "...", "description": "...", "provider": "K8S", "values": {"KEY": "value", ...}}
    The description is optional.
    """
    body = request.json or {}
    if not body.get('label') or not isinstance(body['label'], str):
        raise InvalidRequest("label is required and must be a string")
    try:
        provider = SecretProviderType(body.get('provider'))
    except ValueError:
        raise InvalidRequest(f"provider must be one of {[t.value for t in SecretProviderType]}")
    values = _get_values(body)

    if Secret.query.filter(Secret.label == body['label']).one_or_none():
        raise InvalidRequest(f"Secret {body['label']} already exists", code=HTTPStatus.CONFLICT)

    try:
        secret = Secret(
            label=body['label'],
            provider=provider,
            description=body.get('description'),
            namespace=SecretProvider(provider).namespace,
        )
    except ValueError as e:
        raise InvalidRequest(str(e))

    # The store first, so a failure there leaves no row pointing at nothing. If the row
    # then fails, the stored secret is left for a retry to adopt: writing it overwrites.
    SecretProvider(secret.provider).set(secret.key, secret.namespace, values)
    secret.add()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.CREATED


@bp.route('/<label>', methods=['PATCH'])
@audit
def patch_secret(label):
    """
    PATCH /secrets/<label> — set keys on the stored secret, e.g. to rotate a token. Every
    repository and dataset that references it, in any project, picks the new values up.
    Exempt from the project lock, as a rotation only.
    Body: {"values": {"KEY": "value", ...}}
    """
    secret = _get_secret(label)
    values = _get_values(request.json or {})

    # Written to the provider's current namespace, which the row then records. If that has
    # changed since the secret was created, only these values move: the old copy and any
    # keys not in this request are left behind, so a namespace move means re-creating it.
    store = SecretProvider(secret.provider)
    store.set(secret.key, store.namespace, values)
    secret.namespace = store.namespace
    secret.updated_at = dt.now()
    session.commit()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.OK


@bp.route('/<label>', methods=['DELETE'])
@audit
@auth(scope='can_do_admin', check_dataset=False)
def delete_secret(label):
    """
    DELETE /secrets/<label> — delete the reference and the stored secret. Admin only.
    Refused with a 409 while a repository or dataset still uses it.
    """
    secret = _get_secret(label)
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
        SecretProvider(secret.provider).delete(secret.key, secret.namespace)
    except InvalidRequest:
        session.rollback()
        raise

    session.commit()
    return '', HTTPStatus.NO_CONTENT
