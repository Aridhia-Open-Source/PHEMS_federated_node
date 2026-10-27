import base64
from typing import cast

from kubernetes import client
from kubernetes.client import V1ObjectMeta, V1Secret
from kubernetes.client.exceptions import ApiException
from kubernetes.config import load_incluster_config

from app.models import Secret, SecretProviderType


class K8sSecretProvider:
    """Reads secret values from Kubernetes."""

    def get(self, key: str, namespace: str, value_key: str) -> str:
        """The decoded value stored under value_key in a Kubernetes secret."""
        load_incluster_config()
        v1 = client.CoreV1Api()
        secret = cast(V1Secret, v1.read_namespaced_secret(key, namespace))
        if secret.data is None:
            raise ValueError(f"Secret {key} has no data")
        return base64.b64decode(secret.data[value_key].encode()).decode()


class SecretProvider:
    """Reads secret values from the store the provider name selects."""

    PROVIDERS = {SecretProviderType.K8S: K8sSecretProvider}

    def __init__(self, name: SecretProviderType):
        self.provider = self.PROVIDERS[name]()

    def get(self, key: str, namespace: str, value_key: str) -> str:
        """The value stored under value_key in the secret that the store knows as key."""
        return self.provider.get(key, namespace, value_key)


class TaskSecret:
    """
    A short-lived Kubernetes Secret in the tasks namespace, holding only the credentials of
    one task. The task pod reads it with secretKeyRef, so the values are not in the pod spec.
    Created on entering the block and deleted on leaving it, whether the task succeeded or
    not.
    """

    def __init__(self, name: str, namespace: str, values: dict[str, str]):
        self.name = name
        self.namespace = namespace
        self.values = values

    def __enter__(self):
        load_incluster_config()
        v1 = client.CoreV1Api()
        body = V1Secret(metadata=V1ObjectMeta(name=self.name), string_data=self.values)
        try:
            v1.create_namespaced_secret(self.namespace, body)
        except ApiException as exc:
            if exc.status != 409:
                raise
            # A run that died before it could delete its Secret left this one behind. The
            # Role allows create and delete only, so it is replaced, not patched.
            v1.delete_namespaced_secret(self.name, self.namespace)
            v1.create_namespaced_secret(self.namespace, body)
        return self

    def __exit__(self, *_):
        load_incluster_config()
        client.CoreV1Api().delete_namespaced_secret(self.name, self.namespace)


def read_secret_value(secret: Secret, value_key: str) -> str:
    """The value under value_key of a secret the node has not disabled; a disabled secret is never read."""
    if not secret.enabled:
        raise PermissionError(f"Secret {secret.id} is disabled")
    return SecretProvider(secret.provider).get(secret.key, secret.namespace, value_key)
