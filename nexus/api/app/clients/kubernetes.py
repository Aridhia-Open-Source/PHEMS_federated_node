"""Nexus API adapter for the shared Kubernetes client."""
import os

from kubernetes.client.exceptions import ApiException

from fednode.clients.kubernetes.client import KubernetesClient as SharedKubernetesClient
from app.helpers.exceptions import KubernetesException


class KubernetesClient(SharedKubernetesClient):
    """Select the API pod's Kubernetes environment and retain its error contract."""

    def __init__(self) -> None:
        super().__init__(in_cluster=bool(os.getenv("KUBERNETES_SERVICE_HOST")))

    def create_secret(self, *args, **kwargs):
        try:
            return super().create_secret(*args, **kwargs)
        except ApiException as exc:
            raise KubernetesException(exc.body) from exc

    def patch_secret_data(self, *args, **kwargs):
        try:
            return super().patch_secret_data(*args, **kwargs)
        except ApiException as exc:
            raise KubernetesException(exc.body) from exc
