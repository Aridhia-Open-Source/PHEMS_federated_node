import logging
import json
from datetime import datetime, timedelta
from typing import Any, Literal, Self, Tuple
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.client.models.v1_container_state_terminated import V1ContainerStateTerminated
from kubernetes_asyncio.client.models.v1_container_status import V1ContainerStatus
from kubernetes_asyncio.client.models.v1_job import V1Job
from kubernetes_asyncio.client.models.v1_pod import V1Pod
from kubernetes_asyncio.client.models.v1_pod_list import V1PodList
from sqlalchemy import Integer, DateTime, Select, String, ForeignKey, Boolean, select
from sqlalchemy.orm import Mapped, joinedload, relationship, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from uuid import uuid4

import urllib3
from app.helpers.const import (
    CLEANUP_AFTER_DAYS, CRD_DOMAIN, PUBLIC_URL, TASK_CONTROLLER,
    REVIEW_STATUS, TASK_NAMESPACE, TASK_POD_RESULTS_PATH, RESULTS_PATH
)
from app.helpers.base_model import BaseModel
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesBatchClient, KubernetesCRDClient, KubernetesClient
from app.helpers.exceptions import (
    DBError, InvalidRequest, TaskCRDExecutionException, TaskImageException, TaskExecutionException
)
from app.helpers.task_pod import TaskPod
from app.models.dataset import Dataset
from app.models.container import Container
from app.models.registry import Registry
from app.helpers.container_registries import BaseRegistry
from app.schemas.tasks import TaskRead

logger = logging.getLogger('task_model')
logger.setLevel(logging.INFO)


class Task(BaseModel):
    __tablename__ = 'tasks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    docker_image: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(4096))
    status: Mapped[str] = mapped_column(String(256), default='scheduled')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=True, onupdate=func.now())
    requested_by: Mapped[str] = mapped_column(String(256), nullable=False)
    review_status: Mapped[bool] = mapped_column(Boolean, nullable=True)

    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset: Mapped["Dataset"]  = relationship("Dataset", overlaps="task", lazy='selectin')

    def __init__(self, **kwargs) -> None:
        self.executors = kwargs.pop("executors")
        self.outputs = kwargs.pop("outputs", {})
        self.inputs = kwargs.pop("inputs", {})
        self.is_from_controller = kwargs.pop("from_controller", False)
        self.db_query = kwargs.pop("db_query", {})
        self.resources = kwargs.pop("resources", {})
        self.regcred_secret = kwargs.pop("regcred_secret", "")
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        super().__init__(**kwargs)

    @classmethod
    async def get_by_id(cls, session:AsyncSession, id: int, for_api:bool=False) -> Self:
        q = select(cls).options(joinedload(cls.dataset)).where(cls.id == id)
        task_query_results = await session.execute(q)
        task: Self | None = task_query_results.scalars().one_or_none()
        if for_api:
            return TaskRead.model_validate(task, from_attributes=True).model_copy(
                update={"status": await task.update_status()}
            )
        return task

    @classmethod
    async def split_registry_from_image(cls, session:AsyncSession, docker_image:str) -> tuple[str, str]:
        """
        Find the registry
        """
        for i in range(len(docker_image.split('/'))):
            registry = "/".join(docker_image.split('/')[0:i])

            q = select(func.count(Registry.id)).where(Registry.url == registry)

            if (await session.execute(q)).scalar_one() == 1:
                return registry, "/".join(docker_image.split('/')[i:])

        raise InvalidRequest("Could not find the image in the mapped registries. Check the image has the full name")

    @classmethod
    async def get_image_with_repo(cls, session:AsyncSession, docker_image:str, string_only:bool=True) -> str | Container:
        """
        Looks through the CRs for the image and if exists,
        returns the full image name with the repo prefixing the image.
        """
        registry, image = await cls.split_registry_from_image(session, docker_image)

        tag = None
        sha = None
        if '@' in image:
            image_name, sha = image.split('@')
        else:
            image_name, tag = image.split(':')

        q: Select[Tuple[Container]] = select(Container).options(
            joinedload(Container.registry)
        ).where(
            Container.name==image_name,
            Registry.url == registry,
        ).where(
            (((Container.tag==tag) & (Container.tag is not None)) | ((Container.sha==sha) & (Container.sha is not None)))
        ).join(Registry)
        image:Container = (await session.execute(q)).scalars().one_or_none()

        if image is None:
            raise TaskExecutionException(f"Image {docker_image} could not be found")

        registry_client: BaseRegistry = await image.registry.get_registry_class()
        if not await registry_client.has_image_tag_or_sha(image.name, image.tag, image.sha):
            raise TaskImageException(f"Image {docker_image} not found on our repository")
        if string_only:
            return image.full_image_name()

        return image

    def pod_name(self) -> str:
        """
        Generalization for the pod name based on the task name
        provided by the /tasks API call
        """
        return f"{self.name.lower().replace(' ', '-')}-{uuid4()}"

    def get_expiration_date(self) -> str:
        """
        In order to help with the cleanup process we set a lable for
        - pod
        - pv
        - pvc

        to bulk delete unused resources.
        The date returned is in format `YYYYMMDD`
        Running `kubectl delete pvc -n analytics -l "delete_by=$(date +%Y%m%d)"` will bulk delete
        all pvcs to be deleted today.
        """
        return (datetime.now() + timedelta(days=CLEANUP_AFTER_DAYS)).strftime("%Y%m%d")

    def needs_crd(self) -> str | None | Literal[False]:
        return ((not self.is_from_controller) and TASK_CONTROLLER)

    async def run(self, validate=False) -> None:
        """
        Method to spawn a new pod with the requested image
        : param validate : An optional parameter to basically run in dry_run mode
            Defaults to False
        """
        v1: KubernetesClient = await KubernetesClient.create()
        secret_name = self.dataset.get_creds_secret_name()
        provided_env = self.executors[0].get("env", {})

        command=None
        if len(self.executors):
            command= self.executors[0].get("command", '')

        body: V1Pod = await TaskPod(**{
            "name": self.pod_name(),
            "image": self.docker_image,
            "dataset": self.dataset,
            "db_query": self.db_query,
            "labels": {
                "task_id": str(self.id),
                "requested_by": self.requested_by,
                "dataset_id": str(self.dataset_id),
                "delete_by": self.get_expiration_date()
            },
            "dry_run": 'true' if validate else 'false',
            "environment": provided_env,
            "command": command,
            "mount_path": self.outputs,
            "input_path": self.inputs,
            "resources": self.resources,
            "env_from": v1.create_from_env_object(secret_name),
            "regcred_secret": self.regcred_secret
        }).create_pod_spec()
        try:
            current_pod: V1Pod | None = await self.get_current_pod()
            if current_pod:
                raise TaskExecutionException("Pod is already running", code=409)

            await v1.api_client.create_namespaced_pod(
                namespace=TASK_NAMESPACE,
                body=body,
                pretty='true'
            )
        except ApiException as e:
            logger.error(json.loads(e.body))
            raise InvalidRequest(f"Failed to run pod: {e.reason}") from e

        if self.needs_crd():
            # create CRD
            await self.create_controller_crd()

    async def get_current_pod(self, is_running:bool=True):
        """
        Fetches the pod object from k8s API.
            is_running will only consider running pods only
        """
        v1: KubernetesClient = await KubernetesClient.create()
        running_pods: V1PodList = await v1.api_client.list_namespaced_pod(
            TASK_NAMESPACE,
            label_selector=f"task_id={self.id}"
        )
        try:
            running_pods.items.sort(key=lambda x: x.metadata.creation_timestamp, reverse=True)
            for pod in running_pods.items:
                images: list[str] = [im.image for im in pod.spec.containers]
                statuses = []
                if pod.status.container_statuses and is_running:
                    statuses: list[V1ContainerStateTerminated] = [st.state.terminated for st in pod.status.container_statuses]
                if self.docker_image in images and not statuses:
                    return pod
        except IndexError:
            return

    async def update_status(self):
        """
        k8s sdk returns a bunch of nested objects as a pod's status.
        Here the objects are deconstructed and a customized dictionary is returned
            according to the possible states.
        Returns:
            :dict: if the pod exists
            :str: if the pod is not found or deleted
        """
        status = "pending"
        try:
            status_obj: list[V1ContainerStatus] = (await self.get_current_pod(is_running=False)).status.container_statuses
            if status_obj is None:
                return status

            status_obj = status_obj[0].state

            for status in ['running', 'waiting', 'terminated']:
                st = getattr(status_obj, status)
                if st is not None:
                    break

            returned_status: dict[str, Any] =  {
                "started_at": st.started_at
            }
            if status == 'terminated':
                returned_status.update({
                    "finished_at": getattr(st, "finished_at", None),
                    "exit_code": getattr(st, "exit_code", None),
                    "reason": getattr(st, "reason", None)
                })
            self.status = status
            return {
                status: returned_status
            }
        except AttributeError:
            self.status = status if status != 'running' else 'deleted'

    async def terminate_pod(self, session:AsyncSession) -> None:
        """
        Terminate a pod, checking if during the process
        fails to do so, or is in an errored-out status already
        """
        v1: KubernetesClient = await KubernetesClient.create()
        has_error = False
        try:
            await v1.api_client.delete_namespaced_pod(self.pod_name(), namespace=TASK_NAMESPACE)
        except ApiException as kexc:
            logger.error(kexc.reason)
            has_error = True

        try:
            self.status = 'cancelled'
        except Exception as exc:
            raise DBError("An error occurred while updating") from exc

        if has_error:
            raise TaskExecutionException("Task already cancelled")

    async def get_results(self):
        """
        The idea is to create a job that holds indefinitely
        so that the backend can copy the results
        """
        v1_batch: KubernetesBatchClient = await KubernetesBatchClient.create()
        current_pod: V1Pod | None = await self.get_current_pod(is_running=False)
        job_name: str = f"result-job-{uuid4()}"
        job: V1Job = v1_batch.create_job_spec({
            "name": job_name,
            "persistent_volumes": [
                {
                    "name": f"{current_pod.metadata.name}-volclaim",
                    "mount_path": TASK_POD_RESULTS_PATH,
                    "vol_name": "data",
                    "sub_path": f"{self.id}/results"
                }
            ],
            "labels": {
                "result_task_id": str(self.id),
                "requested_by": self.requested_by
            }
        })
        try:
            await v1_batch.api_client.create_namespaced_job(
                namespace=TASK_NAMESPACE,
                body=job,
                pretty='true'
            )
            # Get the job's pod
            v1: KubernetesClient = await KubernetesClient.create()
            await v1.is_pod_ready(label=f"job-name={job_name}")

            job_pod: V1Pod = (await v1.api_client.list_namespaced_pod(namespace=TASK_NAMESPACE, label_selector=f"job-name={job_name}")).items[0]

            res_file: str = await v1.cp_from_pod(
                pod_name=job_pod.metadata.name,
                source_path=TASK_POD_RESULTS_PATH,
                dest_path=f"{RESULTS_PATH}/{self.id}/results",
                out_name=f"{PUBLIC_URL}-results-{self.id}"
            )
            await v1.delete_pod(job_pod.metadata.name)
            await v1_batch.delete_job(job_name)
        except ApiException as e:
            if 'job_pod' in locals() and await self.get_current_pod(job_pod.metadata.name):
                await v1_batch.delete_job(job_name)
            logger.error(getattr(e, 'reason'))
            raise InvalidRequest(f"Failed to run pod: {e.reason}") from e
        except urllib3.exceptions.MaxRetryError as mre:
            raise InvalidRequest("The cluster could not create the job") from mre
        return res_file

    async def create_controller_crd(self):
        """
        In case this is a task triggered by users
        directly through the API, create a CRD
        so that the task controller can deliver resutls automatically
        Some info like the idp and source is not actively used
        by the controller at this stage, so we populate them
        with default values.

        If the TASK_CONTROLLER env variable is not set, do nothing
        """
        if not TASK_CONTROLLER:
            return

        kc_client: Keycloak = await Keycloak.create()
        crd_client: KubernetesCRDClient = await KubernetesCRDClient.create()
        try:
            await crd_client.api_client.create_cluster_custom_object(
                CRD_DOMAIN, 'v1', 'analytics',
                {
                    "apiVersion": f"{CRD_DOMAIN}/v1",
                    "kind": "Analytics",
                    "metadata": {
                        "annotations": {
                            f"{CRD_DOMAIN}/user": 'ok',
                            f"{CRD_DOMAIN}/task_id": str(self.id),
                            f"{CRD_DOMAIN}/done": 'true'
                        },
                        "name": f"fn-task-{self.id}"
                    },
                    "spec": {
                        "dataset": {"name": self.dataset.name},
                        "image": self.docker_image,
                        "project": "federated_node",
                        "source": {
                            "repository": "Aridhia-Open-Source/PHEMS_federated_node"
                        },
                        "user": {
                            "idpId": "",
                            "username": (await kc_client.get_user_by_id(self.requested_by))["username"]
                        }
                    }
                }
            )
        except ApiException as apie:
            if apie.status != 409:
                raise TaskCRDExecutionException(apie.body, apie.status) from apie

    def get_review_status(self) -> str:
        """
        Simple method to get the review_status
        By default None
            None => not reviewed/needs review
            True => approved
            False => denied/blocked
        """
        return REVIEW_STATUS[self.review_status]

    async def crd_name(self):
        """
        CRD name is set here for consistency's sake
        """
        v1_crds: KubernetesCRDClient = await KubernetesCRDClient.create()
        crds = await v1_crds.api_client.list_cluster_custom_object(
            CRD_DOMAIN, "v1", "analytics"
        )
        for crd in crds["items"]:
            if crd["metadata"]["annotations"].get(f"{CRD_DOMAIN}/task_id") == str(self.id):
                return crd["metadata"]["name"]

    async def get_task_crd(self) -> dict|None:
        """
        Find the CRD associated with the current task.
            Ignore if not found
        """
        crd_client: KubernetesCRDClient = await KubernetesCRDClient.create()
        try:
            return await crd_client.api_client.get_cluster_custom_object(
                CRD_DOMAIN,
                "v1",
                "analytics",
                await self.crd_name()
            )
        except ApiException as apie:
            if apie.status == 404:
                return None
            raise TaskCRDExecutionException(apie.body, apie.status) from apie

    async def update_task_crd(self, approval:bool):
        """
        In case the review happened, update the CRD
        annotation with the appropriate approved value
        """
        crd_client: KubernetesCRDClient = await KubernetesCRDClient.create()
        crd_client.api_client.set_default_header('Content-Type', 'application/json-patch+json')
        try:
            task_crd: dict | None = await self.get_task_crd()
            if not task_crd:
                raise TaskExecutionException("Failed to update result delivery")

            annotations = task_crd["metadata"].get("annotations", {})
            annotations[f"{CRD_DOMAIN}/approved"] = str(approval)
            await crd_client.api_client.patch_cluster_custom_object(
                CRD_DOMAIN, "v1", "analytics", await self.crd_name(),
                [{"op": "add", "path": "/metadata/annotations", "value": annotations}]
            )
        except ApiException as apie:
            raise TaskCRDExecutionException(apie.body, apie.status) from apie

    async def get_logs(self) -> list[str] | Literal['Task queued']:
        """
        Retrieve the pod's logs
        """
        await self.update_status()
        if 'waiting' in self.status:
            return "Task queued"

        pod: V1Pod | None = await self.get_current_pod(is_running=False)
        if pod is None:
            raise TaskExecutionException(f"Task pod {self.id} not found", 400)

        v1: KubernetesClient = await KubernetesClient.create()
        try:
            pod_logs_full = await v1.api_client.read_namespaced_pod_log(
                pod.metadata.name, timestamps=True,
                namespace=TASK_NAMESPACE,
                container=pod.metadata.name
            )
            return pod_logs_full.splitlines()
        except ApiException as apie:
            raise TaskExecutionException("Failed to fetch the logs") from apie
