import os
import logging
import tarfile
from tempfile import TemporaryFile
from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes.client.exceptions import ApiException

from app.helpers.exceptions import InvalidRequest, KubernetesException

logger = logging.getLogger('kubernetes_helper')
logger.setLevel(logging.INFO)

TASK_NAMESPACE = os.getenv("TASK_NAMESPACE")


class KubernetesBase:
    def __init__(self) -> None:
        if os.getenv('KUBERNETES_SERVICE_HOST'):
            # Get configuration for an in-cluster setup
            config.load_incluster_config()
        else:
            # Get config from outside the cluster. Mostly DEV
            config.load_kube_config()
        super().__init__()

    def create_env_from_dict(self, env_dict) -> list[client.V1EnvVar]:
        """
        Kubernetes library accepts env vars as a V1EnvVar
        object. This method converts a dict into V1EnvVar
        """
        env = []
        for k, v in env_dict.items():
            env.append(client.V1EnvVar(name=k, value=str(v)))
        return env

    def create_pod_spec(self, pod_spec:dict):
        """
        Given a dictionary with a pod config deconstruct it
        and assemble it with the different sdk objects
        """
        acr_url = os.getenv('ACR_URL')
        # Create a dedicated VPC for each task so that we can keep results indefinitely
        self.create_persistent_storage(pod_spec["name"])
        pvc_name = f"{pod_spec["name"]}-volclaim"

        vol_mount = client.V1VolumeMount(
            mount_path=pod_spec["mount_path"],
            name="data"
        )
        container = client.V1Container(
            name=pod_spec["name"],
            image=f"{acr_url}/{pod_spec["image"]}",
            env=self.create_env_from_dict(pod_spec.get("environment", {})),
            # For testing purposes now - Should this be dynamic?
            volume_mounts=[vol_mount]
        )
        if pod_spec["command"]:
            container.command = pod_spec["command"]
        secrets = [client.V1LocalObjectReference(name='regcred')]
        pvc = client.V1PersistentVolumeClaimVolumeSource(claim_name=pvc_name)

        specs = client.V1PodSpec(
            containers=[container],
            image_pull_secrets=secrets,
            restart_policy="Never",
            volumes=[client.V1Volume(name="data", persistent_volume_claim=pvc)]
        )
        metadata = client.V1ObjectMeta(
            name=pod_spec["name"],
            namespace=TASK_NAMESPACE,
            labels=pod_spec["labels"]
        )
        return client.V1Pod(
            api_version='v1',
            kind='Pod',
            metadata=metadata,
            spec=specs
        )

    def create_job_spec(self, pod_spec:dict):
        """
        Given a dictionary with a job config deconstruct it
        and assemble it with the different sdk objects
        """
        # Create a dedicated VPC for each task so that we can keep results indefinitely
        volumes = []
        vol_mounts = []
        for pvc in pod_spec["persistent_volumes"]:
            volumes.append(
                client.V1Volume(
                    name=pvc["vol_name"],
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=pvc["name"])
                )
            )
            vol_mounts.append(client.V1VolumeMount(
                mount_path=pvc["mount_path"],
                name=pvc["vol_name"]
            ))
        container = client.V1Container(
            name=pod_spec["name"],
            image="alpine:3.19",
            volume_mounts=vol_mounts,
            command=["tail", "-f", "/dev/null"]
        )
        if pod_spec.get("command"):
            container.command = pod_spec.get("command")

        metadata = client.V1ObjectMeta(
            name=pod_spec["name"],
            namespace=TASK_NAMESPACE,
            labels=pod_spec["labels"]
        )
        specs = client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=volumes
        )
        template = client.V1JobTemplateSpec(
            metadata=metadata,
            spec=specs
        )
        specs = client.V1JobSpec(
            template=template,
            ttl_seconds_after_finished=5
        )
        return client.V1Job(
            api_version='batch/v1',
            kind='Job',
            metadata=metadata,
            spec=specs
        )

    def delete_pod(self, name:str, namespace=TASK_NAMESPACE):
        """
        Given a pod name, delete it. If it doesn't exist
        ignores the exception and logs a message.
        """
        try:
            self.delete_namespaced_pod(
                namespace=namespace,
                name=name
            )
        except ApiException as e:
            logger.error(getattr(e, 'reason'))
            if e.status != 404:
                raise InvalidRequest(f"Failed to delete pod {name}: {e.reason}")

    def delete_job(self, name:str, namespace=TASK_NAMESPACE):
        """
        Given a pod name, delete it. If it doesn't exist
        ignores the exception and logs a message.
        """
        try:
            self.delete_namespaced_job(
                namespace=namespace,
                name=name
            )
        except ApiException as e:
            logger.error(getattr(e, 'reason'))
            if e.status != 404:
                raise InvalidRequest(f"Failed to delete pod {name}: {e.reason}")

    def create_persistent_storage(self, name:str):
        """
        Function to dynamically create (if doesn't already exist)
        a PV and its PVC
        """
        pv = client.V1PersistentVolume(
            api_version='v1',
            kind='PersistentVolume',
            metadata=client.V1ObjectMeta(name=name, namespace=TASK_NAMESPACE),
            spec=client.V1PersistentVolumeSpec(
                access_modes=['ReadWriteMany'],
                capacity={"storage": "100Mi"},
                host_path=client.V1HostPathVolumeSource(path=f"/data/{name}"),
                storage_class_name="shared-results"
            )
        )

        pvc = client.V1PersistentVolumeClaim(
            api_version='v1',
            kind='PersistentVolumeClaim',
            metadata=client.V1ObjectMeta(name=f"{name}-volclaim", namespace=TASK_NAMESPACE),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=['ReadWriteMany'],
                resources=client.V1VolumeResourceRequirements(requests={"storage": "100Mi"})
            )
        )
        try:
            self.create_persistent_volume(body=pv)
            self.create_namespaced_persistent_volume_claim(namespace=TASK_NAMESPACE, body=pvc)
        except ApiException as kexc:
            if kexc.status != 409:
                raise KubernetesException(kexc.body)

    def cp_from_pod(self, pod_name:str, source_path:str, dest_path:str, namespace=TASK_NAMESPACE):
        """
        Method that emulates the `kubectl cp` command
        """
        # cmd to archive the content of source_path to stdout
        exec_command = ['tar', 'cf', '-', source_path]

        try:
            with TemporaryFile() as tar_buffer:
                resp = stream(
                    self.connect_get_namespaced_pod_exec,
                    pod_name, namespace,
                    command=exec_command,
                    stderr=True, stdin=True,
                    stdout=True, tty=False,
                    _preload_content=False
                )
                # Read the stdout from the pod aka the source_path contents
                while resp.is_open():
                    resp.update(timeout=1)
                    if resp.peek_stdout():
                        out = resp.read_stdout()
                        tar_buffer.write(out.encode('utf-8'))
                    if resp.peek_stderr():
                        logger.error("STDERR: %s" % resp.read_stderr())
                resp.close()

                tar_buffer.flush()
                tar_buffer.seek(0)
                try:
                    os.mkdir(dest_path)
                except FileExistsError:
                    # folder exists, skip
                    pass
                # Loop through the contents of the pod's folder
                with tarfile.open(fileobj=tar_buffer, mode='r:') as tar:
                    for member in tar.getmembers():
                        if member.isdir():
                            continue
                        fname = member.name.rsplit('/', 1)[1]
                        tar.makefile(member, dest_path + '/' + fname)

            # Create an archive on the Flask's pod PVC
            results_file_archive = dest_path + '/results.tar.gz'
            with tarfile.open(results_file_archive, "w:gz") as tar:
                tar.add(dest_path, arcname=os.path.basename(dest_path))
        except Exception as e:
            # It's against the standards, but tarfile.ReadError
            # doesn't inherit from BaseException and can't be caught
            # like a normal Exception
            if isinstance(e, tarfile.ReadError):
                raise KubernetesException(str(e))
            raise e

        return results_file_archive

class KubernetesClient(KubernetesBase, client.CoreV1Api):
    pass

class KubernetesBatchClient(KubernetesBase, client.BatchV1Api):
    pass
