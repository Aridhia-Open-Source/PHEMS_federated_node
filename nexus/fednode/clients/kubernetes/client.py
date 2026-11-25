"""Kubernetes API access shared by the node's services."""
import base64
import os
from functools import lru_cache

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


@lru_cache(maxsize=2)
def load_kubernetes_config(*, in_cluster: bool) -> None:
    """Load Kubernetes credentials once for the selected execution environment."""
    if in_cluster:
        config.load_incluster_config()
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
        if no_proxy:
            configuration = client.Configuration.get_default_copy()
            configuration.no_proxy = no_proxy
            client.Configuration.set_default(configuration)
    else:
        config.load_kube_config()


class KubernetesClient(client.CoreV1Api):
    """Core API client configured for either in-cluster or kubeconfig access."""

    def __init__(self, *, in_cluster: bool) -> None:
        load_kubernetes_config(in_cluster=in_cluster)
        super().__init__()

    @classmethod
    def encode_secret_value(cls, value: str) -> str:
        """Base64 encode a plaintext Kubernetes Secret value."""
        return base64.b64encode(value.encode()).decode()

    @classmethod
    def decode_secret_value(cls, value: str) -> str:
        """Decode a base64-encoded Kubernetes Secret value."""
        return base64.b64decode(value.encode()).decode()

    def create_secret(
        self,
        name: str,
        values: dict[str, str],
        namespaces: list[str],
        type: str = "Opaque",
        labels: dict | None = None,
        overwrite: bool = False,
    ) -> client.V1Secret:
        """Create a secret in each namespace, optionally replacing existing data."""
        encoded_values = {key: self.encode_secret_value(value) for key, value in values.items()}
        body = client.V1Secret(
            api_version="v1",
            data=encoded_values,
            kind="Secret",
            metadata={"name": name, "labels": labels or {}},
            type=type,
        )
        for namespace in namespaces:
            try:
                self.create_namespaced_secret(namespace, body=body, pretty="true")
            except ApiException as exc:
                if exc.status != 409:
                    raise
                if overwrite:
                    replacement = {
                        "metadata": body.metadata,
                        "type": body.type,
                        "data": {"$patch": "replace", **body.data},
                    }
                    self.patch_namespaced_secret(name, namespace, body=replacement, pretty="true")
        return body

    def patch_secret_data(self, name: str, namespace: str, values: dict[str, str]) -> None:
        """Update only the named keys of an existing secret."""
        body = {"data": {key: self.encode_secret_value(value) for key, value in values.items()}}
        self.patch_namespaced_secret(name, namespace, body=body)


class KubernetesAppsClient(client.AppsV1Api):
    """Apps API client using the same cached Kubernetes configuration."""

    def __init__(self, *, in_cluster: bool) -> None:
        load_kubernetes_config(in_cluster=in_cluster)
        super().__init__()
