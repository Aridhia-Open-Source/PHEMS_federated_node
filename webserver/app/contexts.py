import contextvars

from app.main import app
from app.helpers.kubernetes_manager import KubernetesBase, get_k8s_base


request_k8s_client = contextvars.ContextVar("k8s_client")


@app.middleware("http")
async def add_k8s_client(request, call_next):
    client: KubernetesBase = await get_k8s_base()
    token = request_k8s_client.set(client)
    try:
        return await call_next(request)
    finally:
        request_k8s_client.reset(token)
