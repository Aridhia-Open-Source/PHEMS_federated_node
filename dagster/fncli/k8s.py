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


CODE_SERVER_CONTAINER = "dagster-code-server"
ENV_CONFIGMAP = "dagster-env-config"


def get_configmap_value(name: str, namespace: str, key: str) -> str | None:
    load_kube_config()
    configmap = client.CoreV1Api().read_namespaced_config_map(name, namespace)
    return (configmap.data or {}).get(key)


def set_configmap_value(name: str, namespace: str, key: str, value: str):
    load_kube_config()
    client.CoreV1Api().patch_namespaced_config_map(name, namespace, {"data": {key: value}})


def restart_code_server(namespace: str, timeout: int = 180):
    """Roll the Dagster code server (the deployment with a dagster-code-server container) and wait until it is ready again."""
    import datetime
    import time

    load_kube_config()
    apps = client.AppsV1Api()
    deployment = next(
        d
        for d in apps.list_namespaced_deployment(namespace).items
        if any(c.name == CODE_SERVER_CONTAINER for c in d.spec.template.spec.containers)
    )
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    apps.patch_namespaced_deployment(
        deployment.metadata.name,
        namespace,
        {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": stamp}}}}},
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = apps.read_namespaced_deployment(deployment.metadata.name, namespace)
        status = current.status
        if (
            current.metadata.generation == status.observed_generation
            and status.updated_replicas == current.spec.replicas
            and status.replicas == current.spec.replicas
            and status.available_replicas == current.spec.replicas
        ):
            # Pod is ready; wait a moment for the location to load in Dagster before returning
            time.sleep(5)
            return
        time.sleep(3)
    raise TimeoutError(f"The code server did not become ready within {timeout}s")
