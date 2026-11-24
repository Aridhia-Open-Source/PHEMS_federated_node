"""
The secret stores: where a secret's values live. The database only keeps a reference (models/secret.py).
"""
import logging

from kubernetes.client.exceptions import ApiException

from app.clients.kubernetes import KubernetesClient
from app.settings import settings
from app.helpers.exceptions import InvalidRequest
from app.models.secret_provider_type import SecretProviderType

logger = logging.getLogger('secret_store')

SECRET_LABELS = {"type": "k8s_secret"}


class K8sSecretProvider:
    """Writes and deletes secrets in Kubernetes."""

    namespace = settings.namespaces.secrets
    quarantine_namespace = settings.namespaces.quarantine

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
        self._move(key, namespace, self.namespaces.quarantine)

    def restore(self, key: str, namespace: str):
        """Moves a secret from the quarantine namespace back into its namespace."""
        self._move(key, self.namespaces.quarantine, namespace)

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
        return self.provider.namespaces.secrets

    @property
    def quarantine_namespace(self) -> str | None:
        return self.provider.namespaces.quarantine

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
