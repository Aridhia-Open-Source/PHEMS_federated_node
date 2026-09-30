from app.models import Dataset, Registry


def build_run_config(spec: dict, dataset: Dataset, registries: list[Registry]) -> dict:
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
    pull_secret = Registry.secret_for_image(image, registries)
    if pull_secret:
        op_config["image_pull_secret"] = pull_secret

    return {"ops": {"k8s_pipes_op": {"config": op_config}}}
