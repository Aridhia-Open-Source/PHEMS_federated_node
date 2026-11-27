"""
The Kubernetes objects of one task run, in the tasks namespace: a Secret with the dataset's credentials
and a ConfigMap with the task's config file. nexus-api creates them when the run asks for them (POST
/projects/<id>/tasks/<id>/runs/<run_id>/resources) and deletes them when the task ends, found by the run
label they carry. Dagster only puts their names in the task pod's spec (dagster/app/definitions/pipes.py):
it never reads, writes or deletes them, and the credentials never pass through it.
"""
import json
from http import HTTPStatus

from kubernetes.client import V1ConfigMap, V1ObjectMeta, V1Secret
from kubernetes.client.exceptions import ApiException
from fednode.clients.kubernetes.client import KubernetesClient

from app.helpers.const import IN_CLUSTER, TASK_NAMESPACE
from app.helpers.exceptions import InvalidRequest
from app.models.task import Task

# On the Secret, the ConfigMap and the task pod. The pod's are set in dagster/app/definitions/pipes.py.
RUN_LABEL = "fn/run_id"
TASK_LABEL = "fn/task_id"

# What the task pod reads from them (dagster/app/definitions/pipes.py): the Secret's USERNAME and PASSWORD through
# secretKeyRef, the ConfigMap's one file as a mounted file.
CONFIG_FILE_NAME = "config.json"


class RunResources:
    """The Secret and the ConfigMap of the run of a task."""

    def __init__(self, task: Task, run_id: str):
        self.task = task
        self.run_id = run_id
        # The run's Secret, and the stem of its ConfigMap's
        self.name = f"task-{task.id}-{run_id}"

    def create(self) -> dict[str, str | None]:
        """
        The Secret of the task's dataset credentials, if it has a dataset, and the ConfigMap of its config file, if
        its spec has a config (an empty one is still one), each labelled with the run and the task. Returns their
        names, None for one that is not needed. A name that is taken is a 409: the run's objects are never replaced.
        """
        labels = {RUN_LABEL: self.run_id, TASK_LABEL: str(self.task.id)}
        k8s = KubernetesClient(in_cluster=IN_CLUSTER)
        names: dict[str, str | None] = {"secret": None, "config_map": None}

        if self.task.spec.dataset_id:
            user, password = self.task.spec.dataset.get_credentials()
            body = V1Secret(
                metadata=V1ObjectMeta(name=self.name, labels=labels), string_data={"USERNAME": user, "PASSWORD": password}
            )
            self._create(k8s.create_namespaced_secret, body, f"Secret {self.name}")
            names["secret"] = self.name
        if self.task.spec.config is not None:
            body = V1ConfigMap(
                metadata=V1ObjectMeta(name=f"{self.name}-config", labels=labels),
                data={CONFIG_FILE_NAME: json.dumps(self.task.spec.config)},
            )
            self._create(k8s.create_namespaced_config_map, body, f"ConfigMap {self.name}-config")
            names["config_map"] = f"{self.name}-config"
        return names

    @staticmethod
    def _create(create, body, what: str):
        try:
            create(TASK_NAMESPACE, body)
        except ApiException as exc:
            if exc.status != HTTPStatus.CONFLICT:
                raise
            raise InvalidRequest(f"{what} already exists in {TASK_NAMESPACE}", HTTPStatus.CONFLICT) from exc

    @classmethod
    def delete(cls, run_id: str):
        """
        Deletes the Secret and the ConfigMap labelled with the run, whichever there are: a run that had no dataset
        or config, or whose objects are gone, leaves nothing to delete and is not an error.
        """
        k8s = KubernetesClient(in_cluster=IN_CLUSTER)
        selector = f"{RUN_LABEL}={run_id}"
        k8s.delete_collection_namespaced_secret(TASK_NAMESPACE, label_selector=selector)
        k8s.delete_collection_namespaced_config_map(TASK_NAMESPACE, label_selector=selector)
