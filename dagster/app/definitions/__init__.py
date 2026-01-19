import dagster as dg
from dagster_celery_k8s import celery_k8s_job_executor

from app.definitions.iris_analysis import iris_dataset_size

defs = dg.Definitions(
    executor=celery_k8s_job_executor,
    assets=[iris_dataset_size]
)
