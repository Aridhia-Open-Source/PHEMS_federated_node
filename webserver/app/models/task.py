import logging
import re
from datetime import datetime
from http import HTTPStatus
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index,
    Integer, JSON, String
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.const import (
    MEMORY_RESOURCE_REGEX, MEMORY_UNITS, CPU_RESOURCE_REGEX, TASK_REVIEW, ENABLE_IMAGE_WHITELIST
)
from app.helpers.base_model import BaseModel, db
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest, NotImplementedException, TaskImageException
from app.models import Models
from app.models.task_status import TriggerSource


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
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    requested_by = Column(String(256), nullable=False)
    review_status = Column(Boolean, nullable=True)
    dataset_id = Column(Integer, ForeignKey('datasets.id', ondelete='CASCADE'))
    dataset = relationship("Dataset")
    # RESTRICT: a project with task history should not be deletable.
    project_id = Column(
        Integer, ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False, index=True
    )
    project = relationship("Project")

    # NOT NULL columns need a server_default: _get_required_fields() would otherwise make
    # them mandatory in the POST /tasks request body.
    trigger_source = Column(String(16), nullable=False, server_default=TriggerSource.API.value)
    pr_repository_id = Column(Integer, nullable=True)
    pr_number = Column(Integer, nullable=True)
    request_id = Column(Integer, ForeignKey('requests.id', ondelete='SET NULL'), nullable=True)

    dagster_run_id = Column(String(64), nullable=True, unique=True)
    started_at = Column(DateTime(timezone=False), nullable=True)
    completed_at = Column(DateTime(timezone=False), nullable=True)
    exit_code = Column(Integer, nullable=True)
    reason = Column(String(256), nullable=True)

    # Relative to the artifacts mount, which is resolved at read time.
    artifact_key = Column(String(512), nullable=True)
    params = Column(JSON, nullable=False, server_default='{}')

    reviewed_by = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime(timezone=False), nullable=True)

    # The check is both-or-neither and not tied to trigger_source: deleting a repository
    # cascades to its PRs, which nulls these columns, and a tied constraint would fail.
    __table_args__ = (
        ForeignKeyConstraint(
            ['pr_repository_id', 'pr_number'],
            ['pull_requests.trigger_repository_id', 'pull_requests.number'],
            ondelete='SET NULL',
            name='fk_tasks_pull_request',
        ),
        CheckConstraint(
            '(pr_repository_id IS NULL) = (pr_number IS NULL)',
            name='ck_tasks_pr_both_or_neither',
        ),
        Index('ix_tasks_dataset_status', 'dataset_id', 'status'),
        Index('ix_tasks_requested_by', 'requested_by'),
        Index('ix_tasks_trigger_source_status', 'trigger_source', 'status'),
        Index('ix_tasks_pull_request', 'pr_repository_id', 'pr_number'),
    )

    def __init__(self,
                 name:str,
                 docker_image:str,
                 requested_by:str,
                 dataset,
                 project_id:int,
                 executors:list[dict] = [],
                 tags:dict = {},
                 resources:dict = {},
                 description:str = '',
                 **kwargs
                 ):
        self.name = name
        self.status = 'scheduled'
        self.docker_image = docker_image
        self.requested_by = requested_by
        self.dataset = dataset
        self.project_id = project_id
        self.description = description
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.tags = tags
        self.executors = executors
        self.resources = resources

    @classmethod
    def validate(cls, data:dict):
        data["name"] = (data.get("name") or "").replace(" ", "")
        if not data["name"]:
            raise InvalidRequest("name is a mandatory field")

        kc_client = Keycloak()
        user_token = Keycloak.get_token_from_headers()

        decoded_token = kc_client.decode_token(user_token)
        data["requested_by"] = kc_client.get_user_by_email(decoded_token["email"])["id"]
        user = kc_client.get_user_by_id(data["requested_by"])
        # Support only for one image at a time, the standard is executors == list
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]
        repository = data.pop("repository", None)

        data = super().validate(data)

        # A task always states which project it belongs to. Delivery and the image
        # allow-list are both scoped to it, so neither resolves without one.
        repo = None
        if repository:
            repo = Models.TriggerRepository.query.filter(
                Models.TriggerRepository.uri == repository.lower()
            ).one_or_none()
            if repo is None:
                raise InvalidRequest(f"No datasets linked with the repository {repository}")
            # The sensor sends no project, so a PR-driven task takes its repository's.
            project = repo.project
        else:
            project = Models.Project.query.filter(
                Models.Project.id == data.get("project_id")
            ).one_or_none()
            if project is None:
                raise InvalidRequest("project_id is a mandatory field")
        data["project_id"] = project.id

        # Dataset validation
        ds_id = data.get("tags", {}).get("dataset_id")
        ds_name = data.get("tags", {}).get("dataset_name")
        requested_ds = None
        if ds_name or ds_id:
            requested_ds = Models.Dataset.get_dataset_by_name_or_id(name=ds_name, id=ds_id)
            # Two ways of saying the same thing must not be allowed to disagree.
            if requested_ds.project_id != project.id:
                raise InvalidRequest(
                    f"Dataset {requested_ds.name} does not belong to project {project.name}"
                )

        if repo:
            # Same rule as the API path: the named dataset if the spec has one, and it has
            # already been checked against the project, otherwise the project's default.
            data["dataset"] = requested_ds or project.default_dataset
            if data["dataset"] is None:
                raise InvalidRequest(
                    f"Project {project.name} has no default dataset. Provide "
                    "`tags.dataset_id` or `tags.dataset_name`"
                )
        elif kc_client.is_user_admin(user_token):
            data["dataset"] = requested_ds or project.default_dataset
            if data["dataset"] is None:
                raise InvalidRequest(
                    f"Project {project.name} has no default dataset. Provide "
                    "`tags.dataset_id` or `tags.dataset_name`"
                )
        else:
            # Naming a dataset does not grant it: an active DAR still has to cover it.
            # Without one, fall back to the single active DAR for the project.
            data["dataset"] = Models.Request.get_active_project(
                data["project_name"],
                user["id"],
                dataset_id=requested_ds.id if requested_ds else None
            ).dataset

        # Docker image validation
        Models.WhitelistedImage.validate_image_format(data["docker_image"], data["docker_image"])

        # Validate that the image is whitelisted for this project
        if ENABLE_IMAGE_WHITELIST:
            if not Models.WhitelistedImage.validate_image_whitelisted(
                data["docker_image"], project.id
            ):
                raise TaskImageException(f"Image {data['docker_image']} is not whitelisted", code=HTTPStatus.FORBIDDEN)

        # Validate that the image exists on the registry
        if not Models.Registry.validate_image_exist(data["docker_image"]):
            raise TaskImageException(
                f"Image {data['docker_image']} not found on our repository", code=HTTPStatus.NOT_FOUND
            )

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

        # Other accepted formats trail with some letters
        unit_index = re.search(r'[^\d]+$', val).span()[0]
        base = val[:unit_index]
        unit = val[unit_index:]
        return int(base) * MEMORY_UNITS[unit]

    def run(self):
        """
        Launches the task
        """
        raise NotImplementedException()

    def get_status(self) -> dict | str:
        """
        Returns the task's status envelope
        """
        raise NotImplementedException()

    def terminate_pod(self):
        """
        Cancels the task
        """
        raise NotImplementedException()

    def get_results(self):
        """
        Returns the path to the task's zipped results
        """
        raise NotImplementedException()

    def get_logs(self):
        """
        Returns the task's logs
        """
        raise NotImplementedException()

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
        The response body, written out rather than derived from the columns.
        """
        return {
            "id": self.id,
            "name": self.name,
            "docker_image": self.docker_image,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.strftime(self.WIRE_DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(self.WIRE_DATETIME_FORMAT),
            "requested_by": self.requested_by,
            "review_status": (
                self.get_review_status() if TASK_REVIEW else self.review_status
            ),
            "dataset_id": self.dataset_id,
            "project_id": self.project_id,
        }
