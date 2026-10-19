"""
Secret endpoints. The values only ever go to the secret store; the database keeps a
reference so that repositories and datasets can share a secret. A secret belongs to no
project and is addressed by its label, which is unique. A project is linked to one under
/projects/<id>/secrets (see projects_api.py). Creating, editing and deleting are admin-only:
- GET /global/secrets
- GET /global/secrets/<label>
- POST /global/secrets
- PATCH /global/secrets/<label>
- DELETE /global/secrets/<label>
- GET /global/secrets/<label>/healthcheck, see healthcheck_api.py
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
bp = Blueprint('secrets', __name__, url_prefix='/global/secrets')
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

    def keys(self, key: str, namespace: str) -> list[str] | None:
        """The names of the keys the secret holds, or None if it is not in the store."""
        try:
            secret = KubernetesClient().read_namespaced_secret(key, namespace)
        except ApiException as apie:
            if apie.status != 404:
                raise
            return None
        return list(secret.data or {})

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

    def keys(self, key: str, namespace: str) -> list[str] | None:
        return self.provider.keys(key, namespace)

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
    GET /global/secrets — list the secrets. The values are never returned.
    """
    return [SecretDTO.from_model(s).dump() for s in Secret.query.order_by(Secret.id)], HTTPStatus.OK


@bp.route('/<label>', methods=['GET'])
def get_secret(label):
    """
    GET /global/secrets/<label> — get a single secret. The values are never returned.
    """
    return SecretDTO.from_model(_get_secret(label)).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_do_admin')
def post_secret():
    """
    POST /global/secrets — create the secret in its store and the reference to it. The label is
    unique across the node; the secret is stored under the generated key
    "fn-secret-<label>", which is fixed from then on. Admin only.
    Body: {"label": "...", "description": "...", "provider": "K8S", "values": {"KEY": "value", ...}, "enabled": true}
    The description and enabled are optional.
    """
    body = request.json or {}
    if not isinstance(body.get('enabled', True), bool):
        raise InvalidRequest("enabled must be a boolean")
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
            enabled=body.get('enabled', True),
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
@auth(scope='can_do_admin')
def patch_secret(label):
    """
    PATCH /global/secrets/<label> — set keys on the stored secret, e.g. to rotate a token, and/or turn
    it on or off (enabled). Every repository and dataset that references it, in any project, picks
    the new values up. Admin only. Turning it off also disables every dataset, trigger repository and
    results repository that uses it, in the same commit; turning it on changes only the secret, those
    stay disabled until each is enabled. Turning off a secret that is off already changes nothing else.
    Body: {"values": {"KEY": "value", ...}, "enabled": true}, any of them.
    """
    secret = _get_secret(label)
    body = request.json or {}
    unknown = set(body) - {"values", "enabled"}
    if unknown and ("values" in body or "enabled" in body):
        raise InvalidRequest(f"Unknown fields: {', '.join(sorted(unknown))}")
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise InvalidRequest("enabled must be a boolean")
        if secret.enabled and not body["enabled"]:
            for resource in (*secret.datasets, *secret.trigger_repositories, *secret.results_repositories):
                resource.enabled = False
        secret.enabled = body["enabled"]

    if "values" in body or "enabled" not in body:
        values = _get_values(body)
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
@auth(scope='can_do_admin')
def delete_secret(label):
    """
    DELETE /global/secrets/<label> — soft delete the reference and revoke and delete its project
    links, and delete the stored secret. Admin only. Refused with a 409 while a repository or
    dataset still uses it.
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
    for assignment in secret.project_assignments:
        assignment.soft_delete()
    secret.soft_delete()

    try:
        SecretProvider(secret.provider).delete(secret.key, secret.namespace)
    except InvalidRequest:
        session.rollback()
        raise

    session.commit()
    return '', HTTPStatus.NO_CONTENT
