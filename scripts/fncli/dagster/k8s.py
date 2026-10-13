import base64
from typing import cast

from kubernetes import client
from kubernetes.client import V1Secret
from kubernetes.config import load_kube_config


def get_k8s_secret(secret_name: str, namespace: str, key: str) -> str:
    """The decoded value stored under key in a Kubernetes secret."""
    load_kube_config()
    v1 = client.CoreV1Api()
    secret = cast(V1Secret, v1.read_namespaced_secret(secret_name, namespace))
    if secret.data is None:
        raise ValueError(f"Secret {secret_name} has no data")
    return base64.b64decode(secret.data[key].encode()).decode()
