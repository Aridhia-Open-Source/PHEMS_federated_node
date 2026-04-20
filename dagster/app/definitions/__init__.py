import dagster as dg
from dagster_k8s import PipesK8sClient

from app.definitions.jobs import jobs
from app.definitions.sensors import sensors
from app.definitions.sensors import github_transfer_job, github_pr_comment_job

pipes_k8s_client = PipesK8sClient(poll_interval=1.0)

defs = dg.Definitions(
    sensors=sensors,
    jobs=[*jobs, github_transfer_job, github_pr_comment_job],
    resources={"k8s_pipes_client": pipes_k8s_client},
)
