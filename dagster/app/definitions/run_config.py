from pydantic import BaseModel

from app.models import Dataset


class K8sPipesOpConfig(BaseModel):
    """The config of k8s_pipes_op: the task's image and env, and the dataset it runs against."""

    env: dict
    docker_image: str
    dataset_name: str
    dataset_host: str
    dataset_port: int
    dataset_type: str
    dataset_read_schema: str | None
    dataset_write_schema: str | None
    dataset_k8s_secret_k8s_name: str


def build_run_config(spec: dict, dataset: Dataset) -> dict:
    """
    The run config for k8s_pipes_job, from a task spec and the dataset it runs against.
    The spec names its image as `image`, or `docker_image` as pull request specs may.
    """
    image = spec.get("image") or spec.get("docker_image")
    if not image:
        raise ValueError("spec missing 'image'")

    op_config = K8sPipesOpConfig(
        env=spec.get("env") or {},
        docker_image=image,
        **dataset.dump_task_fields(),
    )

    return {"ops": {"k8s_pipes_op": {"config": op_config.model_dump()}}}
