import logging
import json
import re
from datetime import datetime, timedelta
from kubernetes.client import V1CustomResourceDefinition
from kubernetes.client.exceptions import ApiException
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4

import urllib3
from app.helpers.const import (
    CLEANUP_AFTER_DAYS, CRD_DOMAIN, MEMORY_RESOURCE_REGEX, MEMORY_UNITS, CPU_RESOURCE_REGEX,
    TASK_NAMESPACE, TASK_POD_RESULTS_PATH, RESULTS_PATH
)
from app.helpers.db import BaseModel, db
from app.helpers.keycloak import Keycloak
from app.helpers.kubernetes import KubernetesBatchClient, KubernetesCRDClient, KubernetesClient
from app.helpers.exceptions import DBError, InvalidRequest, TaskCRDExecutionException, TaskImageException, TaskExecutionException
from app.models.dataset import Dataset
from app.models.container import Container

logger = logging.getLogger('task_model')
logger.setLevel(logging.INFO)


REVIEW_STATUS = {
    True: "Approved Release",
    False: "Blocked Release",
    None: "Pending Review"
}


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
    review_status = Column(Boolean, nullable=True)
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
                 created_at:datetime=datetime.now(),
                 **kwargs
                 ):
        self.name = name
        self.status = 'scheduled'
        self.docker_image = docker_image
        self.requested_by = requested_by
        self.dataset = dataset
        self.description = description
        self.created_at = created_at
        self.updated_at = datetime.now()
        self.tags = tags
        self.executors = executors
        self.resources = resources
        self.inputs = inputs
        self.outputs = outputs
        self.is_from_controller = kwargs.get("from_controller")
        self.deliver_to = kwargs.get("deliver_to")

    @classmethod
    def validate(cls, data:dict):
        data["requested_by"] = Keycloak().decode_token(
            Keycloak.get_token_from_headers()
        ).get('sub')
        # Support only for one image at a time, the standard is executors == list
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]
        is_from_controller = data.pop("task_controller", False)
        deliver_to = data.pop("deliver_to", None)
        # Difference between not providing it (None)
        # and providing an incomplete format. Rest is validated
        # through CRD own validation
        if deliver_to == {} or (not isinstance(deliver_to, dict) and deliver_to is not None):
            raise InvalidRequest("`deliver_to` must have either `git` or `other` as field")

        data = super().validate(data)

        data["deliver_to"] = deliver_to
        data["from_controller"] = is_from_controller
        # Dataset validation
        ds_id = data.get("tags", {}).get("dataset_id")
        ds_name = data.get("tags", {}).get("dataset_name")
        if ds_name or ds_id:
            data["dataset"] = Dataset.get_dataset_by_name_or_id(name=ds_name, id=ds_id)

        # Docker image validation
        if not re.match(r'^((\w+|-|\.)\/?+)+:(\w+(\.|-)?)+$', data["docker_image"]):
            raise InvalidRequest(
                f"{data["docker_image"]} does not have a tag. Please provide one in the format <image>:<tag>"
            )
        data["docker_image"] = cls.get_image_with_repo(data["docker_image"])

        # Output volumes validation
        if not isinstance(data.get("outputs", {}), dict):
            raise InvalidRequest("\"outputs\" filed muct be a json object or dictionary")
        if not data.get("outputs", {}):
            data["outputs"] = {"results": TASK_POD_RESULTS_PATH}

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

    def needs_crd(self):
        return not self.is_from_controller and self.deliver_to

    def run(self, validate=False):
        """
        Method to spawn a new pod with the requested image
        : param validate : An optional parameter to basically run in dry_run mode
            Defaults to False
        """
        v1 = KubernetesClient()
        secret_name = self.dataset.get_creds_secret_name()
        provided_env = self.executors[0]["env"]
        provided_env.update(self.get_db_environment_variables())

        command=None
        if len(self.executors):
            command=self.executors[0].get("command", '')

        body = v1.create_pod_spec({
            "name": self.pod_name(),
            "image": self.docker_image,
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
            "resources": self.resources,
            "env_from": v1.create_from_env_object(secret_name)
        })
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
            raise InvalidRequest(f"Failed to run pod: {e.reason}") from e

        if self.needs_crd():
            self.create_controller_crd()

    def get_db_environment_variables(self) -> dict:
        """
        Creates a dictionary with the standard value for DB credentials
        """
        return {
            "PGHOST": self.dataset.host,
            "PGDATABASE": self.dataset.name,
            "PGPORT": self.dataset.port,
            "MSSQL_HOST": self.dataset.host,
            "MSSQL_DATABASE": self.dataset.name,
            "MSSQL_PORT": self.dataset.port,
            "CONNECTION_ARGS": self.dataset.extra_connection_args
        }

    def get_current_pod(self, is_running:bool=True):
        """
        Fetches the pod object from k8s API.
            is_running will only consider running pods only
        """
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
        """
        Terminate a pod, checking if during the process
        fails to do so, or is in an errored-out status already
        """
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
                    "vol_name": "data"
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

            res_file = v1.cp_from_pod(job_pod.metadata.name, f"{TASK_POD_RESULTS_PATH}/{self.id}", f"{RESULTS_PATH}/{self.id}")
            v1.delete_pod(job_pod.metadata.name)
            v1_batch.delete_job(job_name)
        except ApiException as e:
            if 'job_pod' in locals() and self.get_current_pod(job_pod.metadata.name):
                v1_batch.delete_job(job_name)
            logger.error(getattr(e, 'body'))
            raise InvalidRequest(f"Failed to run pod: {e.reason}") from e
        except urllib3.exceptions.MaxRetryError as e:
            raise InvalidRequest("The cluster could not create the job") from e
        return res_file

    def get_review_status(self) -> str:
        """
        Simple method to get the review_status
        By default None
            None => not reviewed/needs review
            True => approved
            False => denied/blocked
        """
        return REVIEW_STATUS[self.review_status]

    def sanitized_dict(self):
        """
        Extend the method to add custom status and review
        """
        san_dict = super().sanitized_dict()
        san_dict["status"] = self.get_status()
        san_dict["review_status"] = self.get_review_status()
        return san_dict

    def crd_name(self):
        """
        CRD name is set here for consistency's sake
        """
        return f"fn-task-{self.id}"

    def create_controller_crd(self):
        """
        In case this is a task triggered by users
        directly through the API, create a CRD
        so that the task controller can deliver resutls automatically
        Some info like the idp and source is not actively used
        by the controller at this stage, so we populate them
        with default values
        """
        crd_client = KubernetesCRDClient()
        if self.get_task_crd():
            logging.info(f"CRD {self.crd_name()} already exists, skipping")
            return
        try:
            crd_client.create_cluster_custom_object(
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
                        "name": self.crd_name()
                    },
                    "spec": {
                        "dataset": {"name": self.dataset.name},
                        "image": self.docker_image,
                        "project": "federated_node",
                        "source": {
                            "organization": "Aridhia-Open-Source",
                            "repository": "Aridhia-Open-Source/PHEMS_federated_node"
                        },
                        "results": self.deliver_to,
                        "user": {
                            "idpId": self.requested_by,
                            "username": Keycloak().get_user_by_id(self.requested_by)["username"]
                        }
                    }
                }
            )
        except ApiException as apie:
            raise TaskCRDExecutionException(apie.body, apie.status) from apie

    def get_task_crd(self) -> V1CustomResourceDefinition|None:
        """
        Find the CRD associated with the current task.
            Ignore if not found
        """
        crd_client = KubernetesCRDClient()
        try:
            return crd_client.get_cluster_custom_object(CRD_DOMAIN,"v1","analytics",self.crd_name())
        except ApiException as apie:
            if apie.status == 404:
                return None
            raise TaskCRDExecutionException(apie.body, apie.status) from apie

    def update_task_crd(self):
        """
        In case the review happened, update the CRD
        annotation with the appropriate approved value
        """
        crd_client = KubernetesCRDClient()
        crd_client.api_client.set_default_header('Content-Type', 'application/json-patch+json')
        try:
            task_crd = self.get_task_crd()
            if not task_crd:
                raise TaskExecutionException("Failed to update result delivery")

            annotations = task_crd["metadata"].get("annotations", {})
            annotations[f"{CRD_DOMAIN}/approved"] = str(self.review_status)
            crd_client.patch_cluster_custom_object(
                CRD_DOMAIN, "v1", "analytics", self.crd_name(),
                [{"op": "add", "path": "/metadata/annotations", "value": annotations}]
            )
        except ApiException as apie:
            raise TaskCRDExecutionException(apie.body, apie.status) from apie
