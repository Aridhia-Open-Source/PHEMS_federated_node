from pydantic import BaseModel, ConfigDict


class TaskResources(BaseModel):
    """
    The backend's answer to POST /projects/<id>/tasks/<id>/runs/<run_id>/resources: the names of the Secret and
    the ConfigMap it made for the run in the tasks namespace, for the task pod's spec.

    - secret: the Secret of the dataset's credentials; None for a task without a dataset.
    - config_map: the ConfigMap of the task's config file; None for a task without a config.
    """
    model_config = ConfigDict(extra="allow")

    secret: str | None
    config_map: str | None
