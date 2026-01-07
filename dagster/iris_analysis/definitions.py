import dagster as dg
import pandas as pd
from dagster_celery_k8s import celery_k8s_job_executor

celery_k8s_executor = celery_k8s_job_executor.configured(
    {"config_source": {"task_default_queue": "dagster"}}
)

@dg.asset
def iris_dataset_size(context: dg.AssetExecutionContext) -> None:
    df = pd.read_csv(
        "https://docs.dagster.io/assets/iris.csv",
        names=[
            "sepal_length_cm",
            "sepal_width_cm",
            "petal_length_cm",
            "petal_width_cm",
            "species",
        ],
    )

    context.log.info(f"Loaded {df.shape[0]} data points.")


defs = dg.Definitions(
    executor=celery_k8s_executor,
    assets=[iris_dataset_size]
)
