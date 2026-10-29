from pydantic import BaseModel

from app.models import Dataset, SecretProviderType, TaskSpec


class PipesSecretConfig(BaseModel):
    """Where a dataset's secret is: the store that holds it and what it is called there."""

    provider: SecretProviderType
    key: str
    namespace: str | None


class PipesDatasetConfig(BaseModel):
    """The dataset a task runs against, as k8s_pipes_op takes it."""

    name: str
    host: str
    port: int
    type: str
    read_schema: str | None
    write_schema: str | None
    secret: PipesSecretConfig


class K8sPipesOpConfig(BaseModel):
    """The config of k8s_pipes_op: the task's image, env, CPU and memory, and config file content, and the dataset it runs against."""

    env: dict
    compute: dict
    docker_image: str
    config: dict | None = None
    dataset: PipesDatasetConfig | None = None


def build_run_config(spec: TaskSpec, dataset: Dataset | None) -> dict:
    """
    The run config for k8s_pipes_job, from a task spec and the dataset it runs against, if
    any. Without a dataset the config has no dataset key, and without a config file content it has no config key.
    """
    op_config = K8sPipesOpConfig(
        env=spec.env,
        compute=spec.compute,
        docker_image=spec.image,
        config=spec.config,
        dataset=PipesDatasetConfig.model_validate(dataset.model_dump()) if dataset else None,
    )
    absent = {key for key in ("config", "dataset") if getattr(op_config, key) is None}

    return {"ops": {"k8s_pipes_op": {"config": op_config.model_dump(mode="json", exclude=absent)}}}
