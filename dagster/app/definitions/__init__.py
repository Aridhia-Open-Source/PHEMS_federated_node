import dagster as dg
from dagster_k8s import PipesK8sClient
from dagster_celery_k8s import celery_k8s_job_executor

from app.definitions import jobs, pipes, examples, iris_analysis
from app.resources.minio import MinioManager

minio = MinioManager().setup()
asset_modules = [pipes, examples, iris_analysis]
celery_k8s_executor = celery_k8s_job_executor.configured(
    {"config_source": {"task_default_queue": "node"}}
)

defs = dg.Definitions(
    executor=celery_k8s_executor,
    jobs=jobs.asset_jobs,
    assets=dg.load_assets_from_modules(asset_modules),
    resources={
        "io_manager": minio.io_manager,
        "k8s_pipes_client": PipesK8sClient(poll_interval=5.0),
    },
)
