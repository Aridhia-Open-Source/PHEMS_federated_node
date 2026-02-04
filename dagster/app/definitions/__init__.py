import dagster as dg
from dagster_k8s import PipesK8sClient

from app.definitions.jobs import jobs

pipes_k8s_client = PipesK8sClient(poll_interval=1.0)

defs = dg.Definitions(
    jobs=jobs,
    resources={"k8s_pipes_client": pipes_k8s_client},
)
