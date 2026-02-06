from uuid import uuid4
from kubernetes.client import (
    V1ObjectMeta, V1CronJobSpec, V1JobTemplateSpec, V1JobSpec, V1PodTemplateSpec,
    V1CronJobList, V1CronJob, V1JobList, V1Job, V1PodList, V1Pod,
    V1Container, V1ServiceAccountTokenProjection,
    V1VolumeProjection, V1Volume, V1ProjectedVolumeSource,
    V1VolumeMount, V1DownwardAPIProjection, V1DownwardAPIVolumeFile,
    V1ObjectFieldSelector, V1ConfigMapProjection, V1KeyToPath
)
from app.helpers.const import TASK_NAMESPACE, IMAGE_TAG, CRD_DOMAIN
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
    def create_template(cls, name:str, body:V1Pod, schedule:str, crd_name:str) -> V1CronJob:
        """
        Create the k8s V1CronJob object

        Args:
            name: task's name, will be used in the labels to help filtering
            body: it's a normal task's pod, but wrapped inside the
                cronjob -> job -> template
            schedule: the cron rule
        """
        labels:dict = body.metadata.labels
        labels["crd_name"] = crd_name
        # Need to explicitly mount the k8s token manually as k8s
        # can't really do it natively
        creds_vols = [V1Volume(
            name="sa-token",
            projected=V1ProjectedVolumeSource(
                sources=[
                    V1VolumeProjection(
                        service_account_token=V1ServiceAccountTokenProjection(
                            path="token",
                            expiration_seconds=3600
                        )
                    ),
                    V1VolumeProjection(
                        config_map=V1ConfigMapProjection(
                            name="kube-root-ca.crt",
                            items=[
                                V1KeyToPath(
                                    key="ca.crt",
                                    path="ca.crt",
                                )
                            ],
                        )
                    ),
                    V1VolumeProjection(
                        downward_api=V1DownwardAPIProjection(
                            items=[
                                V1DownwardAPIVolumeFile(
                                    path="namespace",
                                    field_ref=V1ObjectFieldSelector(
                                        field_path="metadata.namespace"
                                    ),
                                )
                            ]
                        )
                    )
                ]
            )
        ),
        ]
        body.spec.volumes += creds_vols
        body.spec.service_account_name = "secret-backend-handler"

        # If it's from the controller, let's add an initcontainer
        # to update an annotation every time a new pod is created
        # to trigger monitoring
        body.spec.init_containers.append(
            V1Container(
                name="crd-refresher",
                image=f"ghcr.io/aridhia-open-source/alpine:{IMAGE_TAG}",
                image_pull_policy="Always",
                command=["/bin/sh"],
                args=[
                    "-c",
                    f"kubectl annotate --overwrite analytics {crd_name} {CRD_DOMAIN}/pod_timestamp=$(date +%s)"
                ],
                volume_mounts=[V1VolumeMount(
                    name="sa-token",
                    mount_path="/var/run/secrets/kubernetes.io/serviceaccount",
                    read_only=True
                )]
            )
        )

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
