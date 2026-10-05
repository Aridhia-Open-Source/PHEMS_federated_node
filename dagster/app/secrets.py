from app.k8s import get_k8s_secret
from app.models import SecretType

# How to read a secret's value, by the store it lives in.
READERS = {SecretType.K8S: get_k8s_secret}


def get_secret_value(secret_type: SecretType, store_name: str, namespace: str, key: str) -> str:
    """The value stored under key in a secret, read from the store the secret lives in."""
    return READERS[secret_type](store_name, namespace, key)
