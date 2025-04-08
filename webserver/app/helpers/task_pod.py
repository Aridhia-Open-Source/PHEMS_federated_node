import os
from kubernetes.client import (
    V1Pod, V1PersistentVolumeClaimVolumeSource,
    V1VolumeMount, V1Container,
    V1LocalObjectReference, V1PodSpec,
    V1ObjectMeta, V1Volume, V1PersistentVolumeSpec,
    V1AzureFilePersistentVolumeSource,
    V1HostPathVolumeSource, V1EnvVar,
    V1PersistentVolume, V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec, V1VolumeResourceRequirements
)
from app.helpers.const import TASK_NAMESPACE, TASK_PULL_SECRET_NAME
from app.helpers.kubernetes import KubernetesClient

IMAGE_TAG = os.getenv("IMAGE_TAG")


class TaskPod:
    def __init__(self,
                 name:str,
                 image:str,
                 labels:dict,
                 dry_run:str,
                 environment:dict,
                 command:str,
                 mount_path:dict,
                 resources:dict,
                 env_from:list
                ):
        self.name = name
        self.image = image
        self.labels = labels
        self.dry_run = dry_run
        self.environment = environment
        self.command = command
        self.mount_path = mount_path
        self.resources = resources
        self.env_from = env_from

    def create_env_from_dict(self, env_dict) -> list[V1EnvVar]:
        """
        Kubernetes library accepts env vars as a V1EnvVar
        object. This method converts a dict into V1EnvVar
        """
        env = []
        for k, v in env_dict.items():
            env.append(V1EnvVar(name=k, value=str(v)))
        return env

    def create_storage_specs(self, name:str):
        """
        Function to dynamically create (if doesn't already exist)
        a PV and its PVC
        :param name: is the PV name and PVC prefix
        """
        pv_spec = V1PersistentVolumeSpec(
            access_modes=['ReadWriteMany'],
            capacity={"storage": "100Mi"},
            storage_class_name="shared-results"
        )
        if os.getenv("AZURE_STORAGE_ENABLED"):
            pv_spec.azure_file=V1AzureFilePersistentVolumeSource(
                read_only=False,
                secret_name=os.getenv("AZURE_SECRET_NAME"),
                share_name=os.getenv("AZURE_SHARE_NAME")
            )
        else:
            pv_spec.host_path=V1HostPathVolumeSource(
                path=f"/data/{name}"
            )

        self.pv = V1PersistentVolume(
            api_version='v1',
            kind='PersistentVolume',
            metadata=V1ObjectMeta(name=name, namespace=TASK_NAMESPACE, labels=self.labels),
            spec=pv_spec
        )

        self.pvc = V1PersistentVolumeClaim(
            api_version='v1',
            kind='PersistentVolumeClaim',
            metadata=V1ObjectMeta(name=f"{name}-volclaim", namespace=TASK_NAMESPACE, labels=self.labels),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=['ReadWriteMany'],
                volume_name=name,
                storage_class_name="shared-results",
                resources=V1VolumeResourceRequirements(requests={"storage": "100Mi"})
            )
        )

    def get_task_pod_init_container(self, task_id:str, env_list:list[V1EnvVar]):
        """
        This will return a common spec for initContainer
        fot analytics tasks.
        The aim is to prepare the PV task-dedicated folder
        so the whole volume is not exposed
        """
        mount_path = "/mnt/vol"

        vol_mount = V1VolumeMount(
            mount_path=mount_path,
            name="data"
        )
        dir_init = V1Container(
            name=f"init-{task_id}",
            image="alpine:3.19",
            volume_mounts=[vol_mount],
            command=["mkdir", "-p", f"{mount_path}/{task_id}"]
        )
        data_init = V1Container(
            name="fetch-data",
            image=f"ghcr.io/aridhia-open-source/db_connector:{IMAGE_TAG}",
            volume_mounts=[vol_mount],
            env=env_list
        )
        return [dir_init, data_init]

    def create_pod_spec(self):
        """
        Given a dictionary with a pod config deconstruct it
        and assemble it with the different sdk objects
        """
        # Create a dedicated VPC for each task so that we can keep results indefinitely
        KubernetesClient().create_persistent_storage(self.pv, self.pvc)
        pvc_name = f"{self.name}-volclaim"
        pvc = V1PersistentVolumeClaimVolumeSource(claim_name=pvc_name)

        vol_mounts = []
        # All results volumes will be mounted in a folder named
        # after the task_id, so all of the "output" user-defined
        # folders will be in i.e. /mnt/data/14/folder2
        base_mount_folder = f"{self.labels['task_id']}"

        for mount_name, mount_path in self.mount_path.items():
            vol_mounts.append(V1VolumeMount(
                mount_path=mount_path,
                sub_path=f"{base_mount_folder}/{mount_name}",
                name="data"
            ))
        env=self.create_env_from_dict(self.environment)

        container = V1Container(
            name=self.name,
            image=self.image,
            env=env,
            env_from=self.env_from,
            volume_mounts=vol_mounts,
            image_pull_policy="Always",
            resources=self.resources
        )

        if self.command:
            container.command = self.command

        secrets = [V1LocalObjectReference(name=TASK_PULL_SECRET_NAME)]

        specs = V1PodSpec(
            termination_grace_period_seconds=300,
            init_containers=[self.get_task_pod_init_container(self.labels['task_id'], env)],
            containers=[container],
            image_pull_secrets=secrets,
            restart_policy="Never",
            volumes=[
                V1Volume(name="data", persistent_volume_claim=pvc)
            ]
        )
        metadata = V1ObjectMeta(
            name=self.name,
            namespace=TASK_NAMESPACE,
            labels=self.labels
        )
        return V1Pod(
            api_version='v1',
            kind='Pod',
            metadata=metadata,
            spec=specs
        )
