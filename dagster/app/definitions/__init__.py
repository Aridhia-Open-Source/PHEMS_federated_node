import dagster as dg
from dagster_k8s import PipesK8sClient

from app.definitions.jobs import jobs
from app.definitions.sensors import transfer_job, k8s_pipes_sensor

pipes_k8s_client = PipesK8sClient(poll_interval=1.0)

defs = dg.Definitions(
    jobs=[*jobs, transfer_job],
    sensors=[k8s_pipes_sensor],
    resources={"k8s_pipes_client": pipes_k8s_client},
)
