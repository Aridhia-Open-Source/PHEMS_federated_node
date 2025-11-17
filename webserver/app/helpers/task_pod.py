import os
from kubernetes.client import (
    V1Pod, V1PersistentVolumeClaimVolumeSource,
    V1VolumeMount, V1Container,
    V1LocalObjectReference, V1PodSpec,
    V1ObjectMeta, V1Volume, V1PersistentVolumeSpec,
    V1AzureFilePersistentVolumeSource,
    V1HostPathVolumeSource, V1EnvVar,
    V1PersistentVolume, V1PersistentVolumeClaim,
    V1EnvVarSource, V1SecretKeySelector,
    V1PersistentVolumeClaimSpec, V1VolumeResourceRequirements,
    V1CSIPersistentVolumeSource
)
from app.helpers.const import RESULTS_PATH, STORAGE_CLASS, TASK_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from app.models.dataset import Dataset

IMAGE_TAG = os.getenv("IMAGE_TAG")


class TaskPod:
    base_mount_path = "/mnt/vol"

    def __init__(
            self,
            name:str,
            image:str,
            dataset:Dataset,
            labels:dict,
            dry_run:str,
            environment:dict,
            command:str,
            mount_path:dict,
            input_path:dict,
            resources:dict,
            env_from:list,
            db_query:dict,
            regcred_secret:str
        ):
        self.name = name
        self.image = image
        self.dataset = dataset
        self.labels = labels
        self.dry_run = dry_run
        self.command = command
        self.mount_path = mount_path
        self.input_path = input_path
        self.resources = resources
        self.env_from = env_from
        self.db_query = db_query
        self.regcred_secret = regcred_secret
        self.env = []
        self.env_init = []
        self.create_env_from_dict(environment)

    def create_env_from_dict(self, env) -> list[V1EnvVar]:
        """
        Kubernetes library accepts env vars as a V1EnvVar
        object. This method converts a dict into V1EnvVar
        """
        for k, v in env.items():
            self.env.append(V1EnvVar(name=k, value=str(v)))

    def create_db_env_vars(self):
        """
        From a secret name, setup a base env list with db credentials.
        It will map PG_* for backwards compatibility
        """
        secret_name = self.dataset.get_creds_secret_name()
        self.env_init += [
            V1EnvVar(
                name="DB_PSW",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=secret_name,
                        key="PGPASSWORD",
                        optional=True
                    )
                )
            ),
            V1EnvVar(
                name="DB_USER",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=secret_name,
                        key="PGUSER",
                        optional=True
                    )
                )
            ),
            V1EnvVar(name="DB_PORT", value=str(self.dataset.port)),
            V1EnvVar(name="DB_NAME", value=self.dataset.name),
            V1EnvVar(name="DB_SCHEMA", value=self.dataset.schema),
            V1EnvVar(name="DB_ARGS", value=self.dataset.extra_connection_args),
            V1EnvVar(name="DB_HOST", value=self.dataset.host)
        ]

    def create_storage_specs(self):
        """
        Function to dynamically create (if doesn't already exist)
        a PV and its PVC
        :param name: is the PV name and PVC prefix
        """
        pv_spec = V1PersistentVolumeSpec(
            access_modes=['ReadWriteMany'],
            capacity={"storage": os.getenv("CLAIM_CAPACITY")},
            storage_class_name=STORAGE_CLASS
        )
        if os.getenv("AZURE_STORAGE_ENABLED"):
            pv_spec.azure_file=V1AzureFilePersistentVolumeSource(
                read_only=False,
                secret_name=os.getenv("AZURE_SECRET_NAME"),
                share_name=os.getenv("AZURE_SHARE_NAME")
            )
        elif os.getenv("AWS_STORAGE_ENABLED"):
            pv_spec.csi=V1CSIPersistentVolumeSource(
                driver=os.getenv("AWS_STORAGE_DRIVER"),
                volume_handle=os.getenv("AWS_FILES_SYSTEM_ID")
            )
        else:
            pv_spec.host_path=V1HostPathVolumeSource(
                path=RESULTS_PATH
            )

        self.pv = V1PersistentVolume(
            api_version='v1',
            kind='PersistentVolume',
            metadata=V1ObjectMeta(name=self.name, namespace=TASK_NAMESPACE, labels=self.labels),
            spec=pv_spec
        )

        self.pvc = V1PersistentVolumeClaim(
            api_version='v1',
            kind='PersistentVolumeClaim',
            metadata=V1ObjectMeta(name=f"{self.name}-volclaim", namespace=TASK_NAMESPACE, labels=self.labels),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=['ReadWriteMany'],
                volume_name=self.name,
                storage_class_name=STORAGE_CLASS,
                resources=V1VolumeResourceRequirements(requests={"storage": "100Mi"})
            )
        )

    def get_task_pod_init_container(self, task_id:str):
        """
        This will return a common spec for initContainer
        fot analytics tasks.
        The aim is to prepare the PV task-dedicated folder
        so the whole volume is not exposed
        """
        self.create_db_env_vars()
        self.env_init.append(V1EnvVar(name="INPUT_MOUNT", value=f"{self.base_mount_path}/{task_id}/input"))
        if self.input_path:
            self.env_init.append(V1EnvVar(name="INPUT_FILE", value=list(self.input_path.keys())[0]))

        vol_mount = V1VolumeMount(
            mount_path=self.base_mount_path,
            name="data"
        )
        dir_init = V1Container(
            name=f"init-{task_id}",
            image="alpine:3.19",
            volume_mounts=[vol_mount],
            command=["/bin/sh"],
            args=[
                "-c",
                f"mkdir -p {self.base_mount_path}/{task_id}/results {self.base_mount_path}/{task_id}/input;"
                f"chmod 777 {self.base_mount_path}/{task_id}/input;"
                f"ls -la {self.base_mount_path}/{task_id}"
            ]
        )
        init_containers = [dir_init]

        if self.db_query:
            data_init = V1Container(
                name="fetch-data",
                image=f"ghcr.io/aridhia-open-source/db_connector:{IMAGE_TAG}",
                volume_mounts=[vol_mount],
                image_pull_policy="Always",
                env=self.env_init,
                env_from=self.env_from
            )
            init_containers.append(data_init)
        return init_containers

    def create_pod_spec(self):
        """
        Given a dictionary with a pod config deconstruct it
        and assemble it with the different sdk objects
        """
        # Create a dedicated VPC for each task so that we can keep results indefinitely
        self.create_storage_specs()
        KubernetesClient().create_persistent_storage(self.pv, self.pvc)
        pvc_name = f"{self.name}-volclaim"
        pvc = V1PersistentVolumeClaimVolumeSource(claim_name=pvc_name)

        vol_mounts = []
        # All results volumes will be mounted in a folder named
        # after the task_id, so all of the "output" user-defined
        # folders will be in i.e. /mnt/data/14/folder2
        task_id = self.labels['task_id']

        # input mount
        for in_name, in_path in self.input_path.items():
            vol_mounts.append(V1VolumeMount(
                    mount_path=in_path,
                    sub_path=f"{task_id}/input",
                    name="data"
                ))
            if "INPUT_PATH" not in [env.name for env in self.env]:
                self.env.append(V1EnvVar(name="INPUT_PATH", value=f"{in_path}/{in_name}"))

        for mount_name, mount_path in self.mount_path.items():
            vol_mounts.append(V1VolumeMount(
                mount_path=mount_path,
                sub_path=f"{task_id}/{mount_name}",
                name="data"
            ))

        if self.db_query:
            self.env_init.append(V1EnvVar(name="QUERY", value=self.db_query["query"]))
            self.env_init.append(V1EnvVar(name="FROM_DIALECT", value=self.db_query["dialect"]))
            self.env_init.append(V1EnvVar(name="TO_DIALECT", value=self.dataset.type))

        self.env.append(V1EnvVar(name="CONNECTION_STRING", value=self.dataset.get_connection_string()))
        self.env.append(V1EnvVar(name="ORACLE_SID", value=self.dataset.name))
        container = V1Container(
            name=self.name,
            image=self.image,
            env=self.env,
            volume_mounts=vol_mounts,
            image_pull_policy="Always",
            resources=self.resources
        )

        if self.command:
            container.command = self.command

        secrets = [V1LocalObjectReference(name=self.regcred_secret)]

        specs = V1PodSpec(
            termination_grace_period_seconds=300,
            init_containers=self.get_task_pod_init_container(self.labels['task_id']),
            containers=[container],
            image_pull_secrets=secrets,
            restart_policy="Never",
            automount_service_account_token=False,
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
