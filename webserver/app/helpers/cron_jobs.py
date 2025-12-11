from uuid import uuid4
from kubernetes.client import (
    V1ObjectMeta, V1CronJobSpec, V1JobTemplateSpec, V1JobSpec, V1PodTemplateSpec,
    V1CronJobList, V1CronJob, V1JobList, V1Job, V1PodList, V1Pod
)
from app.helpers.const import TASK_NAMESPACE
from app.helpers.kubernetes import KubernetesBatchClient, KubernetesClient


class CronJob:
    def __init__(self, task_id:int):
        self.task_id = task_id

    def get(self) -> V1CronJob:
        """
        Fetches the cronjob
        """
        batch_v1 = KubernetesBatchClient()
        cj_list:V1CronJobList = batch_v1.list_namespaced_cron_job(
            namespace=TASK_NAMESPACE,
            label_selector=f"task_id={self.task_id}"
        ).items
        if cj_list:
            return cj_list[0]

    def get_job(self) -> V1Job:
        """
        Returns the job related to the cronjob/task id
        """
        batch_v1 = KubernetesBatchClient()
        list_jobs:V1JobList = batch_v1.list_namespaced_job(namespace=TASK_NAMESPACE, label_selector=f"task_id={self.task_id}").items
        if list_jobs:
            return list_jobs[0]

    def get_all_pods(self) -> list[V1Pod]:
        """
        Returns the list of pods related to the cronjob/task id
        """
        v1 = KubernetesClient()
        running_pods:V1PodList = v1.list_namespaced_pod(
            TASK_NAMESPACE,
            label_selector=f"task_id={self.task_id}"
        )
        running_pods.items.sort(key=lambda x: x.metadata.creation_timestamp, reverse=True)
        return running_pods.items

    def get_all_logs(self):
        """
        Gets all the pods' logs in a dictionary format
            where keys are the numbered pods, i.e.
            ```python
            {"pod_1": "log line", "pod_2": "another line"}
            ```
        """
        v1 = KubernetesClient()
        pods: list[V1Pod] = self.get_all_pods()
        logs = dict()
        for idx, pod in enumerate(pods):
            logs[f"pod_{idx}"] = v1.read_namespaced_pod_log(
                pod.metadata.name, timestamps=True,
                namespace=TASK_NAMESPACE,
                container=pod.spec.containers[0].name
            ).splitlines()
        return logs

    def get_pvc_name(self) -> str:
        """
        Returns the CronJob Persistent Volume Claim name
        """
        return self.get().spec.job_template.spec.template.spec.volumes[0].persistent_volume_claim.claim_name

    @classmethod
    def create_template(cls, name:str, body:V1Pod, schedule:str) -> V1CronJob:
        """
        Create the k8s V1CronJob object

        Args:
            name: task's name, will be used in the labels to help filtering
            body: it's a normal task's pod, but wrapped inside the
                cronjob -> job -> template
            schedule: the cron rule
        """
        labels:dict = body.metadata.labels

        labels["name"] = name
        return V1CronJob(
            api_version="batch/v1",
            kind="CronJob",
            metadata=V1ObjectMeta(
                name=f"cron-{uuid4()}",
                namespace=TASK_NAMESPACE,
                labels=labels
            ),
            spec=V1CronJobSpec(
                failed_jobs_history_limit=1,
                successful_jobs_history_limit=1,
                job_template=V1JobTemplateSpec(
                    spec=V1JobSpec(
                        template=V1PodTemplateSpec(
                            metadata=V1ObjectMeta(
                                labels=labels
                            ),
                            spec=body.spec
                        )
                    )
                ),
                schedule=schedule,
            )
        )
