from app.models import Dataset


def build_run_config(spec: dict, dataset: Dataset) -> dict:
    """
    The run config for k8s_pipes_job, from a task spec and the dataset it runs against.
    The spec names its image as `image`, or `docker_image` as pull request specs may.
    """
    image = spec.get("image") or spec.get("docker_image")
    if not image:
        raise ValueError("spec missing 'image'")

    op_config = {
        "env": spec.get("env") or {},
        "docker_image": image,
        **dataset.dump_task_fields(),
    }

    return {"ops": {"k8s_pipes_op": {"config": op_config}}}
