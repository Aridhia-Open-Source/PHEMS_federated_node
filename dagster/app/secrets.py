from app.k8s import get_k8s_secret
from app.models import SecretProvider

# How to read a secret's value, by the store it lives in.
READERS = {SecretProvider.K8S: get_k8s_secret}


def get_secret_value(provider: SecretProvider, secret_key: str, namespace: str, key: str) -> str:
    """The value stored under key in a secret, read from the store the secret lives in."""
    return READERS[provider](secret_key, namespace, key)
