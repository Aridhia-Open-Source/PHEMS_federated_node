import base64
from typing import cast

from kubernetes import client
from kubernetes.client import V1Secret
from kubernetes.config import load_incluster_config

from app.models import SecretProviderType


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
