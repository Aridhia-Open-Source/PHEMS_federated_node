import base64
import io
import logging
import os
import shutil
import tarfile
from typing import Generic, Self, Type, TypeVar, get_args
from aiohttp import WSMessage, WSMsgType
from kubernetes_asyncio import client, stream
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.watch import Watch
from app.helpers.exceptions import InvalidRequest, KubernetesException
from app.helpers.const import ALPINE_IMAGE, TASK_NAMESPACE
from app.helpers.kubernetes_manager import KubernetesBase, get_k8s_base


logger = logging.getLogger('kubernetes_helper')
logger.setLevel(logging.INFO)

T = TypeVar("T", client.CustomObjectsApi, client.BatchV1Api, client.CoreV1Api)


class BaseClient(Generic[T]):
    api_client: T = None

    def __init__(self, api_client: T) -> None:
        self.api_client = api_client

    @classmethod
    async def create(cls: Type[Self]) -> Self:
        """This replaces the async __init__"""
        generic_parent = cls.__orig_bases__[0]
        actual_type = get_args(generic_parent)[0]
        base: KubernetesBase = await get_k8s_base(actual_type)
        return cls(base.api_client)

    @classmethod
    def encode_secret_value(cls, value:str) -> str:
        """
        Given a plain text secret it will perform the
        base64 encoding
        """
        return base64.b64encode(value.encode()).decode()

    @classmethod
    def decode_secret_value(cls, value:str) -> str:
        """
        Given a plain text secret it will perform the
        base64 decoding
        """
        return base64.b64decode(value.encode()).decode()

    def create_from_env_object(self, secret_name) -> list[client.V1EnvFromSource]:
        """
        From a secret name, setup a EnvFrom object
        """
        return [client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name=secret_name))]

    def create_job_spec(self, pod_spec:dict) -> client.V1Job:
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
                name=pvc["vol_name"],
                sub_path=pvc["sub_path"]
            ))
        container = client.V1Container(
            name=pod_spec["name"],
            image=ALPINE_IMAGE,
            volume_mounts=vol_mounts,
            command=["/bin/sh", "-c", f"sleep {60*60*24}"]
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


class KubernetesClient(BaseClient[client.CoreV1Api]):
    async def create_persistent_storage(
            self,
            task_pv:client.V1PersistentVolume,
            task_pvc:client.V1PersistentVolumeClaim
        ) -> None:
        """
        Function to dynamically create (if doesn't already exist)
        a PV and its PVC
        :param name: is the PV name and PVC prefix
        """
        try:
            await self.api_client.create_persistent_volume(body=task_pv)
        except ApiException as kexc:
            if kexc.status != 409:
                raise KubernetesException(kexc.body) from kexc
        try:
            await self.api_client.create_namespaced_persistent_volume_claim(namespace=TASK_NAMESPACE, body=task_pvc)
        except ApiException as kexc:
            if kexc.status != 409:
                raise KubernetesException(kexc.body) from kexc

    async def is_pod_ready(self, label) -> None:
        """
        By getting a label, checks if the pod is in ready state.
        Once this happens the method will return
        """
        watcher = Watch()
        async for event in watcher.stream(
            func=self.api_client.list_namespaced_pod,
            namespace=TASK_NAMESPACE,
            label_selector=label,
            timeout_seconds=60
        ):
            if event["object"].status.phase == "Running":
                watcher.stop()
                break
            logger.info(f"Pod is in state {event["object"].status.phase}")

    async def create_secret(
            self,
            name:str,
            values:dict[str, str],
            namespaces:list,
            type:str='Opaque',
            labels:dict={}
        ) -> client.V1Secret:
        """
        From a dict of values, encodes them,
            and creates a secret in a given list of namespace
            keeping the same structure as values
        """
        body = client.V1Secret()
        body.api_version = 'v1'
        for key in values.keys():
            values[key] = self.encode_secret_value(values[key])

        body.data = values
        body.kind = 'Secret'
        body.metadata = {
            'name': name,
            'labels': labels
        }
        body.type = type
        for ns in namespaces:
            try:
                await self.api_client.create_namespaced_secret(ns, body=body, pretty='true')
            except ApiException as e:
                if e.status != 409:
                    raise KubernetesException(e.body)
        return body

    async def delete_pod(self, name:str, namespace=TASK_NAMESPACE) -> None:
        """
        Given a pod name, delete it. If it doesn't exist
        ignores the exception and logs a message.
        """
        try:
            await self.api_client.delete_namespaced_pod(
                namespace=namespace,
                name=name
            )
        except ApiException as e:
            if e.status != 404:
                raise InvalidRequest(f"Failed to delete pod {name}: {e.reason}") from e

    async def cp_from_pod(self, pod_name:str, source_path:str, dest_path:str, out_name:str, namespace=TASK_NAMESPACE) -> str:
        """
        Method that emulates the `kubectl cp` command
        """
        # Make sure the tmp/data folder exists so that the zip files is not in the same folder
        # as the actual results
        os.makedirs("/tmp/data", exist_ok=True)
        try:
            ws_client = stream.WsApiClient()
            api = client.CoreV1Api(ws_client)

            # cmd to archive the content of source_path to stdout
            command = [
                "tar",
                "cf",
                "-",
                source_path
            ]

            resp = await api.connect_get_namespaced_pod_exec(
                name=pod_name,
                namespace=namespace,
                command=command,
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False
            )

            tar_buffer = io.BytesIO()

            async with resp as ws:
                # Read the stdout from the pod aka the source_path contents
                while True:
                    message:WSMessage = await ws.receive()
                    if message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break

                    if len(message.data) > 1:
                        tar_buffer.write(message.data[1:])

            tar_buffer.flush()
            tar_buffer.seek(0)
            results_file_archive = f'/tmp/data/{out_name}'

            try:
                os.makedirs(dest_path, exist_ok=True)
                os.remove(results_file_archive)
            except (FileExistsError, FileNotFoundError):
                # folder exists, skip
                pass

            with tarfile.open(fileobj=tar_buffer, mode='r:') as tar:
                # Loop through the contents of the pod's folder
                for member in tar.getmembers():
                    fname = member.name.replace(source_path[1:], "")
                    if fname:
                        if member.isdir():
                            tar.makedir(member, dest_path + '/' + fname[1:])
                        else:
                            tar.makefile(member, dest_path + '/' + fname[1:])

            # Create an archive on the Flask's pod PVC
            shutil.make_archive(results_file_archive, 'zip', dest_path)
        except NotADirectoryError as nde:
            logger.error("%s %s %s", nde.filename, nde.filename, nde.strerror)
            raise KubernetesException("Error creating the zip file") from nde
        except Exception as e:
            raise KubernetesException(getattr(e, "strerror", "")) from e

        return f"{results_file_archive}.zip"

class KubernetesBatchClient(BaseClient[client.BatchV1Api]):

    async def delete_job(self, name:str, namespace=TASK_NAMESPACE) -> None:
        """
        Given a pod name, delete it. If it doesn't exist
        ignores the exception and logs a message.
        """
        try:
            await self.api_client.delete_namespaced_job(
                namespace=namespace,
                name=name
            )
        except ApiException as e:
            if e.status != 404:
                raise InvalidRequest(f"Failed to delete pod {name}: {e.reason}") from e


class KubernetesCRDClient(BaseClient[client.CustomObjectsApi]):
    pass
