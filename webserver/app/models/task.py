import logging
import json
import re
from datetime import datetime, timedelta
from kubernetes.client.exceptions import ApiException
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4

import urllib3
from app.helpers.const import (
    CLEANUP_AFTER_DAYS, MEMORY_RESOURCE_REGEX, MEMORY_UNITS, CPU_RESOURCE_REGEX,
    TASK_NAMESPACE, TASK_POD_RESULTS_PATH, TASK_POD_INPUTS_PATH, RESULTS_PATH
)
from app.helpers.base_model import BaseModel, db
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesBatchClient, KubernetesClient
from app.helpers.exceptions import DBError, InvalidRequest, TaskImageException, TaskExecutionException
from app.helpers.task_pod import TaskPod
from app.models.dataset import Dataset
from app.models.container import Container
from app.models.request import Request

logger = logging.getLogger('task_model')
logger.setLevel(logging.INFO)


class Task(db.Model, BaseModel):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    docker_image = Column(String(256), nullable=False)
    description = Column(String(4096))
    status = Column(String(256), default='scheduled')
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())
    requested_by = Column(String(256), nullable=False)
    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")

    def __init__(self,
                 name:str,
                 docker_image:str,
                 requested_by:str,
                 dataset:Dataset,
                 executors:dict = {},
                 tags:dict = {},
                 resources:dict = {},
                 inputs:dict = {},
                 outputs:dict = {},
                 description:str = '',
                 **kwargs
                 ):
        self.name = name
        self.status = 'scheduled'
        self.docker_image = docker_image
        self.requested_by = requested_by
        self.dataset = dataset
        self.description = description
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.tags = tags
        self.executors = executors
        self.resources = resources
        self.inputs = inputs
        self.outputs = outputs
        self.db_query = kwargs.get("db_query", {})

    @classmethod
    def validate(cls, data:dict):
        kc_client = Keycloak()
        user_token = Keycloak.get_token_from_headers()
        data["requested_by"] = kc_client.decode_token(user_token).get('sub')
        user = kc_client.get_user_by_id(data["requested_by"])
        # Support only for one image at a time, the standard is executors == list
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]
        data = super().validate(data)

        # Dataset validation
        if kc_client.is_user_admin(user_token):
            ds_id = data.get("tags", {}).get("dataset_id")
            ds_name = data.get("tags", {}).get("dataset_name")
            if ds_name or ds_id:
                data["dataset"] = Dataset.get_dataset_by_name_or_id(name=ds_name, id=ds_id)
            else:
                raise InvalidRequest("Administrators need to provide `tags.dataset_id` or `tags.dataset_name`")
        else:
            data["dataset"] = Request.get_active_project(
                data["project_name"],
                user["id"]
            ).dataset

        # Docker image validation
        if not re.match(r'^((\w+|-|\.)\/?+)+:(\w+(\.|-)?)+$', data["docker_image"]):
            raise InvalidRequest(
                f"{data["docker_image"]} does not have a tag. Please provide one in the format <image>:<tag>"
            )
        data["docker_image"] = cls.get_image_with_repo(data["docker_image"])

        # Output volumes validation
        if not isinstance(data.get("outputs", {}), dict):
            raise InvalidRequest("\"outputs\" field must be a json object or dictionary")
        if not data.get("outputs", {}):
            data["outputs"] = {"results": TASK_POD_RESULTS_PATH}
        if not isinstance(data.get("inputs", {}), dict):
            raise InvalidRequest("\"inputs\" field must be a json object or dictionary")
        if not data.get("inputs", {}):
            data["inputs"] = {"inputs.csv": TASK_POD_INPUTS_PATH}

        # Validate resource values
        if "resources" in data:
            cls.validate_cpu_resources(
                data["resources"].get("limits", {}).get("cpu"),
                data["resources"].get("requests", {}).get("cpu")
            )
            cls.validate_memory_resources(
                data["resources"].get("limits", {}).get("memory"),
                data["resources"].get("requests", {}).get("memory")
            )
        data["db_query"] = data.pop("db_query")
        return data

    @classmethod
    def validate_cpu_resources(cls, limit_value:str, request_value:str):
        """
        Given a value for the cpu limits or requests, make sure it conforms to
        accepted k8s values.
        e.g.
            - 100m
            - 0.1
            - 1
        """
        for value in [limit_value, request_value]:
            if value is None or value == "":
                return
            cpu_error_message = f"Cpu resource value {value} not valid."
            if not re.match(CPU_RESOURCE_REGEX, value):
                raise InvalidRequest(cpu_error_message)
        if cls.convert_cpu_values_to_int(limit_value) < cls.convert_cpu_values_to_int(request_value):
            raise InvalidRequest("Cpu limit cannot be lower than request")

    @classmethod
    def validate_memory_resources(cls, limit_value:str, request_value:str):
        """
        Given a value for the memory limits or requests, make sure it conforms to
        accepted k8s values.
        e.g.
            - 128974848
            - 129e6
            - 129M
            - 128974848000m
            - 123Mi
        """
        for value in [limit_value, request_value]:
            if value is None or value == "":
                return
            memory_error_msg = f"Memory resource value {value} not valid."
            if not re.match(MEMORY_RESOURCE_REGEX, value):
                raise InvalidRequest(memory_error_msg)
        if cls.convert_memory_values_to_int(limit_value) < cls.convert_memory_values_to_int(request_value):
            raise InvalidRequest("Memory limit cannot be lower than request")

    @classmethod
    def convert_cpu_values_to_int(cls, val:str) -> float:
        """
        Since cpu values can come with different units,
        they should be standardized to float, so that they can
        be compared and validated to have limits > requests
        """
        if re.match(r'^\d+$', val):
            return float(val)
        if re.match(r'^\d+\.\d+$', val):
            return float(val)
        return float(val[:-1]) / 1000

    @classmethod
    def convert_memory_values_to_int(cls, val:str) -> int:
        """
        Since memory values can come with different units,
        they should be standardized to int, so that they can
        be compared and validated to have limits > requests
        """
        if re.match(r'^\d+$', val):
            return int(val)
        if re.match(r'^\d+e\d+$', val):
            base, exp = val.split('e')
            return int(base) * 10**(int(exp))
        base = val[:-2]
        unit = val[-2:]
        return int(base) * MEMORY_UNITS[unit]

    @classmethod
    def get_image_with_repo(cls, docker_image):
        """
        Looks through the CRs for the image and if exists,
        returns the full image name with the repo prefixing the image.
        """
        image_name = "/".join(docker_image.split('/')[1:])
        image_name, tag = image_name.split(':')
        image = Container.query.filter(Container.name==image_name, Container.tag==tag).one_or_none()
        if image is None:
            raise TaskExecutionException(f"Image {docker_image} could not be found")

        registry_client = image.registry.get_registry_class()
        if not registry_client.get_image_tags(image.name):
            raise TaskImageException(f"Image {docker_image} not found on our repository")

        return image.full_image_name()

    def pod_name(self):
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

    def run(self, validate=False):
        """
        Method to spawn a new pod with the requested image
        : param validate : An optional parameter to basically run in dry_run mode
            Defaults to False
        """
        v1 = KubernetesClient()
        secret_name = self.dataset.get_creds_secret_name()
        provided_env = self.executors[0].get("env", {})

        command=None
        if len(self.executors):
            command=self.executors[0].get("command", '')

        body = TaskPod(**{
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
            "env_from": v1.create_from_env_object(secret_name)
        }).create_pod_spec()
        try:
            current_pod = self.get_current_pod()
            if current_pod:
                raise TaskExecutionException("Pod is already running", code=409)

            v1.create_namespaced_pod(
                namespace=TASK_NAMESPACE,
                body=body,
                pretty='true'
            )
        except ApiException as e:
            logger.error(json.loads(e.body))
            raise InvalidRequest(f"Failed to run pod: {e.reason}")

    def get_current_pod(self, is_running:bool=True):
        v1 = KubernetesClient()
        running_pods = v1.list_namespaced_pod(
            TASK_NAMESPACE,
            label_selector=f"task_id={self.id}"
        )
        try:
            running_pods.items.sort(key=lambda x: x.metadata.creation_timestamp, reverse=True)
            for pod in running_pods.items:
                images = [im.image for im in pod.spec.containers]
                statuses = []
                if pod.status.container_statuses and is_running:
                    statuses = [st.state.terminated for st in pod.status.container_statuses]
                if self.docker_image in images and not statuses:
                    return pod
        except IndexError:
            return

    def get_status(self) -> dict | str:
        """
        k8s sdk returns a bunch of nested objects as a pod's status.
        Here the objects are deconstructed and a customized dictionary is returned
            according to the possible states.
        Returns:
            :dict: if the pod exists
            :str: if the pod is not found or deleted
        """
        try:
            status_obj = self.get_current_pod(is_running=False).status.container_statuses
            if status_obj is None:
                return self.status

            status_obj = status_obj[0].state

            for status in ['running', 'waiting', 'terminated']:
                st = getattr(status_obj, status)
                if st is not None:
                    break

            self.status = status
            returned_status =  {
                "started_at": st.started_at
            }
            if status == 'terminated':
                returned_status.update({
                    "finished_at": getattr(st, "finished_at", None),
                    "exit_code": getattr(st, "exit_code", None),
                    "reason": getattr(st, "reason", None)
                })
            return {
                status: returned_status
            }
        except AttributeError:
            return self.status if self.status != 'running' else 'deleted'

    def terminate_pod(self):
        v1 = KubernetesClient()
        has_error = False
        try:
            v1.delete_namespaced_pod(self.pod_name(), namespace=TASK_NAMESPACE)
        except ApiException as kexc:
            logger.error(kexc.reason)
            has_error = True

        try:
            self.status = 'cancelled'
        except Exception as exc:
            raise DBError("An error occurred while updating") from exc

        if has_error:
            raise TaskExecutionException("Task already cancelled")
        return self.sanitized_dict()

    def get_results(self):
        """
        The idea is to create a job that holds indefinitely
        so that the backend can copy the results
        """
        v1_batch = KubernetesBatchClient()
        job_name = f"result-job-{uuid4()}"
        job = v1_batch.create_job_spec({
            "name": job_name,
            "persistent_volumes": [
                {
                    "name": f"{self.get_current_pod(is_running=False).metadata.name}-volclaim",
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
            v1_batch.create_namespaced_job(
                namespace=TASK_NAMESPACE,
                body=job,
                pretty='true'
            )
            # Get the job's pod
            v1 = KubernetesClient()
            v1.is_pod_ready(label=f"job-name={job_name}")

            job_pod = v1.list_namespaced_pod(namespace=TASK_NAMESPACE, label_selector=f"job-name={job_name}").items[0]

            res_file = v1.cp_from_pod(
                job_pod.metadata.name,
                TASK_POD_RESULTS_PATH,
                f"{RESULTS_PATH}/{self.id}/results"
            )
            v1.delete_pod(job_pod.metadata.name)
            v1_batch.delete_job(job_name)
        except ApiException as e:
            if 'job_pod' in locals() and self.get_current_pod(job_pod.metadata.name):
                v1_batch.delete_job(job_name)
            logger.error(getattr(e, 'reason'))
            raise InvalidRequest(f"Failed to run pod: {e.reason}")
        except urllib3.exceptions.MaxRetryError:
            raise InvalidRequest("The cluster could not create the job")
        return res_file

    def get_logs(self):
        """
        Retrieve the pod's logs
        """
        if 'waiting' in self.get_status():
            return "Task queued"

        pod = self.get_current_pod(is_running=False)
        if pod is None:
            raise TaskExecutionException(f"Task pod {self.id} not found", 400)

        v1 = KubernetesClient()
        try:
            return v1.read_namespaced_pod_log(
                pod.metadata.name, timestamps=True,
                namespace=TASK_NAMESPACE,
                container=pod.metadata.name
            ).splitlines()
        except ApiException as apie:
            logger.error(apie)
            raise TaskExecutionException("Failed to fetch the logs") from apie
