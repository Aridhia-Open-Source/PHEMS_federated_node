import base64
from typing import cast

from kubernetes import client
from kubernetes.client import V1Secret
from kubernetes.client.exceptions import ApiException
from kubernetes.config import list_kube_config_contexts, load_kube_config

# The node config resources (ADR 0032)
GROUP = "fn.aridhia.com"
VERSION = "v1alpha1"


def current_context() -> str:
    """The name of the kubectl context that cluster secrets are read from"""
    return list_kube_config_contexts()[1]["name"]


def get_k8s_secret(secret_name: str, namespace: str, key: str) -> str:
    """The decoded value stored under key in a Kubernetes secret."""
    load_kube_config()
    v1 = client.CoreV1Api()
    secret = cast(V1Secret, v1.read_namespaced_secret(secret_name, namespace))
    if secret.data is None:
        raise ValueError(f"Secret {secret_name} has no data")
    return base64.b64decode(secret.data[key].encode()).decode()


def k8s_secret_version(secret_name: str, namespace: str) -> str | None:
    """The resourceVersion of a Kubernetes secret, None when there is none"""
    load_kube_config()
    try:
        return client.CoreV1Api().read_namespaced_secret(secret_name, namespace).metadata.resource_version
    except ApiException as error:
        if error.status == 404:
            return None
        raise


def write_k8s_secret(secret_name: str, namespace: str, values: dict[str, str]) -> str:
    """Create or replace a Kubernetes secret with exactly these values; returns its new resourceVersion"""
    load_kube_config()
    v1 = client.CoreV1Api()
    body = client.V1Secret(metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace), string_data=values)
    if k8s_secret_version(secret_name, namespace) is None:
        return v1.create_namespaced_secret(namespace, body).metadata.resource_version
    return v1.replace_namespaced_secret(secret_name, namespace, body).metadata.resource_version


def list_node_config(plural: str) -> list[dict]:
    """Every fn.aridhia.com resource of a kind, in every namespace"""
    load_kube_config()
    return client.CustomObjectsApi().list_cluster_custom_object(GROUP, VERSION, plural)["items"]


def get_node_config(plural: str, namespace: str, name: str) -> dict | None:
    """One fn.aridhia.com resource, None when there is none"""
    load_kube_config()
    try:
        return client.CustomObjectsApi().get_namespaced_custom_object(GROUP, VERSION, namespace, plural, name)
    except ApiException as error:
        if error.status == 404:
            return None
        raise


def patch_node_config(plural: str, namespace: str, name: str, operations: list[dict]) -> dict:
    """A JSON patch of one fn.aridhia.com resource; returns the resource as patched"""
    load_kube_config()
    return client.CustomObjectsApi().patch_namespaced_custom_object(GROUP, VERSION, namespace, plural, name, operations)


def remove_k8s_secret_keys(secret_name: str, namespace: str, keys: list[str]):
    """Remove keys from a Kubernetes secret and leave the others as they are."""
    load_kube_config()
    client.CoreV1Api().patch_namespaced_secret(secret_name, namespace, {"data": {key: None for key in keys}})


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
            return
        time.sleep(3)
    raise TimeoutError(f"The code server did not become ready within {timeout}s")
