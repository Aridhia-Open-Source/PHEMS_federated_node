import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import logging
from kubernetes_asyncio import client, config


logger = logging.getLogger('kubernetes_manager')
logger.setLevel(logging.INFO)


executor = ThreadPoolExecutor(max_workers=4)
_lock = asyncio.Lock()


class KubernetesBase:
    def __init__(self) -> None:
        self.api_client = None

    async def initialize(self, base_class: client.CustomObjectsApi|client.BatchV1Api|client.CoreV1Api) -> None:
        if os.getenv('KUBERNETES_SERVICE_HOST'):
            # Get configuration for an in-cluster setup
            await config.load_incluster_config()
        else:
            # Get config from outside the cluster. Mostly DEV
            await config.load_kube_config()
        self.api_client = base_class()


_k8s_base = KubernetesBase()

async def get_k8s_base(base_class: client.CustomObjectsApi|client.BatchV1Api|client.CoreV1Api) -> KubernetesBase:
    if _k8s_base.api_client is None:
        async with _lock:
            # Double-check inside the lock
            if _k8s_base.api_client is None:
                await _k8s_base.initialize(base_class)
    return _k8s_base

