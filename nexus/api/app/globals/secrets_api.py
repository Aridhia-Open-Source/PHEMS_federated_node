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
- GET /global/secrets/<label>/healthcheck
"""
from datetime import datetime as dt
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends

from app.dtos.secret import SecretDTO
from app.database.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.clients.kubernetes_names import validate_secret_key
from app.clients.secret_store import SecretProvider
from app.rules.ownership import get_for_write, require_members, set_owner
from app.database.soft_delete import describe_project
from app.helpers.wrappers import Caller, get_caller
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.dtos.healthcheck import SecretHealthDTO
from app.health.secrets import prepare_secret_health

router = APIRouter(prefix='/global/secrets', tags=["secrets"])
session = db.session

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


def _get_secret(label: str) -> Secret:
    secret = Secret.query.filter(Secret.label == label).one_or_none()
    if not secret:
        raise DBRecordNotFoundError(f"Secret {label} does not exist")
    return secret


@router.get('', response_model=list[SecretDTO])
def get_secrets():
    """
    GET /global/secrets — list the secrets. The values are never returned.
    """
    return [SecretDTO.from_model(s) for s in Secret.query.order_by(Secret.id)]


@router.get('/{label}', response_model=SecretDTO)
def get_secret(label: str):
    """
    GET /global/secrets/<label> — get a single secret. The values are never returned.
    """
    return SecretDTO.from_model(_get_secret(label))


@router.post('', status_code=HTTPStatus.CREATED, response_model=SecretDTO)
def post_secret(body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    POST /global/secrets — create the secret in its store and the reference to it. The label is
    unique across the node; the secret is stored under the generated key
    "fn-secret-<label>", which is fixed from then on. Admin only.
    Body: {"label": "...", "description": "...", "provider": "K8S", "values": {"KEY": "value", ...}, "enabled": true}
    The description and enabled are optional.
    """
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
    set_owner(secret, caller)
    secret.add()

    return SecretDTO.from_model(secret)


@router.patch('/{label}', response_model=SecretDTO)
def patch_secret(label: str, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /global/secrets/<label> — replace the stored values, e.g. to rotate a token, and/or turn it on
    or off (enabled). The secret then holds exactly these keys, so send every key it needs: any other,
    such as a cached git token, is dropped. Every repository and dataset that references it, in any
    project, picks the new values up. Admin only. Turning it off also disables every dataset, trigger repository and
    results repository that uses it, in the same commit; turning it on changes only the secret, those
    stay disabled until each is enabled. Turning off a secret that is off already changes nothing else.
    Turning it off moves its stored value to the quarantine namespace and turning it on moves it back,
    before anything is committed: if the move fails so does the request, and nothing has changed. The
    row keeps the secret's own namespace, which is what makes it unreadable there meanwhile. A disabled
    secret cannot be rotated (409), unless the same request turns it on. Rotation comes before the move
    when both are asked for.
    Body: {"values": {"KEY": "value", ...}, "enabled": true}, any of them.
    """
    secret = get_for_write(session, Secret, {"label": label}, caller, missing=f"Secret {label} does not exist")
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
        # changed since the secret was created, only these values move: the old copy is left
        # behind, so a namespace move means re-creating it.
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

    return SecretDTO.from_model(secret)


@router.delete('/{label}', status_code=HTTPStatus.NO_CONTENT)
def delete_secret(label: str, force: bool = False, caller: Caller = Depends(get_caller)):
    """
    DELETE /global/secrets/<label> — soft delete the reference and revoke and delete its project
    resources, and delete the stored secret, from its namespace and from quarantine. Admin only. Refused
    with a 409 naming the enabled datasets and repositories that still use it: they have to be
    disabled first, unless ?force=true, which disables them and goes on. Disabled ones may stay
    pointing at it, and can be repointed with their secret_label.
    """
    secret = get_for_write(session, Secret, {"label": label}, caller, missing=f"Secret {label} does not exist")
    enabled = [(dataset.name, dataset) for dataset in secret.datasets if dataset.enabled] + [
        (repository.uri, repository)
        for repository in (*secret.trigger_repositories, *secret.results_repositories) if repository.enabled
    ]
    if enabled and not force:
        raise InvalidRequest(
            f"Secret {secret.label} is still used by enabled datasets or repositories: "
            f"{', '.join(name for name, _ in enabled)}. Disable them first or delete with ?force=true",
            code=HTTPStatus.CONFLICT
        )

    require_members(secret.project_assignments, caller, describe_project)

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


@router.get('/{label}/healthcheck', response_model=SecretHealthDTO)
def secret_healthcheck(label: str):
    """
    GET /global/secrets/<label>/healthcheck endpoint. Whether the secret is in its store with the
    keys its datasets and repositories need. Never the values.
    """
    return prepare_secret_health(_get_secret(label))()
