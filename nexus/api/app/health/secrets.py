"""
Secret health: is it in its store with the keys its users need (a git credential is any complete set of
keys: see repos/git_tokens.py). Never the values.
"""
from collections.abc import Callable

from app.clients.secret_store import SecretProvider
from app.dtos.healthcheck import ProjectSecretHealthDTO, SecretHealthDTO
from app.health.run import health_check_dto
from app.models.dataset import Dataset
from app.models.git_provider import ConnectionCheck, ConnectionStatus
from app.models.project_secret import ProjectSecret
from app.models.secret import Secret
from app.repos.git_tokens import missing_credential_keys


def _missing_keys(secret: Secret, keys: list[str]) -> set[str]:
    """
    What the secret's users need and it lacks: a dataset's USERNAME and PASSWORD, and for a repository the nearest
    complete git credential (a GitHub App, a Gitea OAuth2 application or a TOKEN), none if it holds one.
    """
    missing = set()
    if secret.datasets:
        missing |= set(Dataset.SECRET_KEYS) - set(keys)
    if secret.trigger_repositories or secret.results_repositories:
        missing |= missing_credential_keys(keys)
    return missing

def prepare_secret_health(secret: Secret) -> Callable[[], SecretHealthDTO]:
    """
    A global secret: is it in its store, with the keys its datasets and repositories read.
    A secret nothing uses needs no particular key. A disabled one is reported as not readable
    (secret_missing, saying it is disabled) without looking in the store, its value being in quarantine.
    """
    if not secret.enabled:
        # Its value is in quarantine, out of reach on purpose: not read
        keys = []
        check = ConnectionCheck(ConnectionStatus.SECRET_MISSING, f"Secret {secret.label} is disabled, so it cannot be read")
    else:
        keys = SecretProvider(secret.provider).keys(secret.key, secret.namespace)
        if keys is None:
            check = ConnectionCheck(ConnectionStatus.SECRET_MISSING, f"Secret {secret.label} is not in its store")
            keys = []
        elif missing := _missing_keys(secret, keys):
            check = ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {secret.label} has no {', '.join(sorted(missing))}"
            )
        else:
            check = ConnectionCheck(ConnectionStatus.OK, "OK")
    health = SecretHealthDTO(
        label=secret.label, provider=secret.provider, enabled=secret.enabled,
        status=check.status.value, health_check=health_check_dto(check),
        keys=sorted(keys), missing_keys=sorted(_missing_keys(secret, keys)),
    )
    return lambda: health

def prepare_secret_resource_health(resource: ProjectSecret) -> Callable[[], ProjectSecretHealthDTO]:
    secret = prepare_secret_health(resource.secret)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    return lambda: ProjectSecretHealthDTO(
        project_id=project_id, enabled=enabled, revoked=revoked, active=active, secret=secret()
    )
