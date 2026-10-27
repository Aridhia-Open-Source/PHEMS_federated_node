"""
Secret endpoints. The values only ever go to the secret store; the database keeps a
reference so that repositories and datasets can share a secret. A secret belongs to no
project and is addressed by its label, which is unique. A project is assigned one under
/projects/<id>/secrets (see projects_api.py). Creating, editing and deleting are admin-only. A disabled
secret's value is moved out of its namespace into a quarantine namespace (QUARANTINE_NAMESPACE), so nothing
reading the secret where the row says it is can get it, and moved back when the secret is enabled again:
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
from app.helpers.const import QUARANTINE_NAMESPACE, SECRETS_NAMESPACE
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

    namespace = SECRETS_NAMESPACE
    quarantine_namespace = QUARANTINE_NAMESPACE

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

    def quarantine(self, key: str, namespace: str):
        """Moves a secret from its namespace into the quarantine namespace."""
        self._move(key, namespace, self.quarantine_namespace)

    def restore(self, key: str, namespace: str):
        """Moves a secret from the quarantine namespace back into its namespace."""
        self._move(key, self.quarantine_namespace, namespace)

    def _move(self, key: str, source: str, target: str):
        """
        Kubernetes cannot move a secret: copy it, then delete the original, so that a failure
        in between leaves the value in both places and not in neither. A secret that is not in
        the source is already where it should be (or is not in the store at all): nothing to do,
        which also makes a repeated move safe. The copy overwrites, so it replaces what an
        earlier move that failed after the copy left in the target.
        """
        try:
            data = KubernetesClient().read_namespaced_secret(key, source).data or {}
        except ApiException as apie:
            if apie.status == 404:
                return
            logger.error(apie)
            raise InvalidRequest("Could not move the secret") from apie
        values = {name: KubernetesClient.decode_secret_value(value) for name, value in data.items()}
        KubernetesClient().create_secret(
            name=key, values=values, namespaces=[target], labels=SECRET_LABELS, overwrite=True
        )
        self.delete(key, source)


class SecretProvider:
    """Writes and deletes secret values in the store the provider name selects."""

    PROVIDERS = {SecretProviderType.K8S: K8sSecretProvider}

    def __init__(self, name: SecretProviderType):
        self.provider = self.PROVIDERS[name]()

    @property
    def namespace(self) -> str | None:
        return self.provider.namespace

    @property
    def quarantine_namespace(self) -> str | None:
        return self.provider.quarantine_namespace

    def set(self, key: str, namespace: str, values: dict[str, str]):
        self.provider.set(key, namespace, values)

    def quarantine(self, key: str, namespace: str):
        self.provider.quarantine(key, namespace)

    def restore(self, key: str, namespace: str):
        self.provider.restore(key, namespace)

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
    # One created disabled goes straight to quarantine, as if it had been disabled after.
    store = SecretProvider(secret.provider)
    store.set(secret.key, secret.namespace if secret.enabled else store.quarantine_namespace, values)
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
    Turning it off moves its stored value to the quarantine namespace and turning it on moves it back,
    before anything is committed: if the move fails so does the request, and nothing has changed. The
    row keeps the secret's own namespace, which is what makes it unreadable there meanwhile. A disabled
    secret cannot be rotated (409), unless the same request turns it on. Rotation comes before the move
    when both are asked for.
    Body: {"values": {"KEY": "value", ...}, "enabled": true}, any of them.
    """
    secret = _get_secret(label)
    body = request.json or {}
    unknown = set(body) - {"values", "enabled"}
    if unknown and ("values" in body or "enabled" in body):
        raise InvalidRequest(f"Unknown fields: {', '.join(sorted(unknown))}")
    if "enabled" in body and not isinstance(body["enabled"], bool):
        raise InvalidRequest("enabled must be a boolean")
    values = _get_values(body) if "values" in body or "enabled" not in body else None
    turning_on = body.get("enabled") is True and not secret.enabled
    turning_off = body.get("enabled") is False and secret.enabled
    if values and not secret.enabled and not turning_on:
        raise InvalidRequest(
            f"Secret {secret.label} is disabled: enable it before rotating it", code=HTTPStatus.CONFLICT
        )

    # The store first, and the row only once it has all succeeded: each step is safe to repeat.
    store = SecretProvider(secret.provider)
    namespace = secret.namespace
    if turning_on:
        store.restore(secret.key, namespace)
    if values:
        # Written to the provider's current namespace, which the row then records. If that has
        # changed since the secret was created, only these values move: the old copy and any
        # keys not in this request are left behind, so a namespace move means re-creating it.
        namespace = store.namespace
        store.set(secret.key, namespace, values)
    if turning_off:
        store.quarantine(secret.key, namespace)
        for resource in (*secret.datasets, *secret.trigger_repositories, *secret.results_repositories):
            resource.enabled = False
    if "enabled" in body:
        secret.enabled = body["enabled"]
    secret.namespace = namespace
    secret.updated_at = dt.now()
    session.commit()

    return SecretDTO.from_model(secret).dump(), HTTPStatus.OK


@bp.route('/<label>', methods=['DELETE'])
@audit
@auth(scope='can_do_admin')
def delete_secret(label):
    """
    DELETE /global/secrets/<label> — soft delete the reference and revoke and delete its project
    resources, and delete the stored secret, from its namespace and from quarantine. Admin only. Refused
    with a 409 naming the enabled datasets and repositories that still use it: they have to be
    disabled first, unless ?force=true, which disables them and goes on. Disabled ones may stay
    pointing at it, and can be repointed with their secret_label.
    """
    secret = _get_secret(label)
    enabled = [(dataset.name, dataset) for dataset in secret.datasets if dataset.enabled] + [
        (repository.uri, repository)
        for repository in (*secret.trigger_repositories, *secret.results_repositories) if repository.enabled
    ]
    if enabled and request.args.get("force", "").lower() != "true":
        raise InvalidRequest(
            f"Secret {secret.label} is still used by enabled datasets or repositories: "
            f"{', '.join(name for name, _ in enabled)}. Disable them first or delete with ?force=true",
            code=HTTPStatus.CONFLICT
        )

    # Staged, not committed: if the store delete fails the row has to come back, and a
    # rollback after a commit is a no-op.
    for _, resource in enabled:
        resource.enabled = False
    for assignment in secret.project_assignments:
        assignment.soft_delete()
    secret.soft_delete()

    store = SecretProvider(secret.provider)
    try:
        store.delete(secret.key, secret.namespace)
        # Wherever it is: a disabled secret's value is only there, and one that was
        # being moved when something failed may be in both.
        store.delete(secret.key, store.quarantine_namespace)
    except InvalidRequest:
        session.rollback()
        raise

    session.commit()
    return '', HTTPStatus.NO_CONTENT
