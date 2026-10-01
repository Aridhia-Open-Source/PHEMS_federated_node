import logging
import re
from datetime import datetime as dt
from http import HTTPStatus

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.const import (
    MEMORY_RESOURCE_REGEX, MEMORY_UNITS, CPU_RESOURCE_REGEX, ENABLE_IMAGE_WHITELIST
)
from app.helpers.base_model import BaseModel, db
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest, NotImplementedException, TaskImageException
from app.models import Models, sqla_column


logger = logging.getLogger('task_model')
logger.setLevel(logging.INFO)


class Task(db.Model, BaseModel):
    __tablename__ = 'tasks'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False, index=True
    )
    pr_repository_id = sa.Column(sa.Integer, nullable=True)
    pr_number = sa.Column(sa.Integer, nullable=True)
    request_id = sa.Column(sa.Integer, sa.ForeignKey('requests.id', ondelete='SET NULL'), nullable=True)
    api_request_id = sa.Column(sa.Integer, sa.ForeignKey('api_requests.id', ondelete='SET NULL'), nullable=True)
    task_request_id = sa.Column(
        sa.Integer, sa.ForeignKey('task_requests.id', ondelete='RESTRICT', name='fk_tasks_task_request'), nullable=True
    )

    name = sa.Column(sa.String(256), nullable=False)
    docker_image = sa.Column(sa.String(256), nullable=False)
    status = sa.Column(sa.String(256), default='scheduled')
    requested_by = sa.Column(sa.String(256), nullable=False)
    dagster_run_id = sa.Column(sa.String(64), nullable=True, unique=True)
    exit_code = sa.Column(sa.Integer, nullable=True)

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()
    started_at = sa.Column(sa.DateTime(timezone=False), nullable=True)
    completed_at = sa.Column(sa.DateTime(timezone=False), nullable=True)

    params = sa.Column(sa.JSON, nullable=False, server_default='{}')

    dataset = relationship("Dataset")
    project = relationship("Project")
    api_request = relationship("ApiRequest", back_populates="tasks")
    task_request = relationship("TaskRequest", back_populates="task")

    __table_args__ = (
        sa.UniqueConstraint('task_request_id', name='uq_tasks_task_request'),
        sa.ForeignKeyConstraint(
            ['pr_repository_id', 'pr_number'],
            ['pull_requests.trigger_repository_id', 'pull_requests.number'],
            ondelete='SET NULL',
            name='fk_tasks_pull_request',
        ),
        sa.CheckConstraint(
            '(pr_repository_id IS NULL) = (pr_number IS NULL)',
            name='ck_tasks_pr_both_or_neither',
        ),
        sa.Index('ix_tasks_dataset_status', 'dataset_id', 'status'),
        sa.Index('ix_tasks_requested_by', 'requested_by'),
        sa.Index('ix_tasks_pull_request', 'pr_repository_id', 'pr_number'),
    )

    def __init__(self,
                 name:str,
                 docker_image:str,
                 requested_by:str,
                 dataset_id:int | None,
                 project_id:int,
                 task_request_id:int | None = None,
                 api_request_id:int | None = None,
                 pr_repository_id:int | None = None,
                 pr_number:int | None = None,
                 params:dict | None = None,
                 ):
        self.name = name
        self.status = 'scheduled'
        self.docker_image = docker_image
        self.requested_by = requested_by
        self.dataset_id = dataset_id
        self.project_id = project_id
        self.task_request_id = task_request_id
        self.api_request_id = api_request_id
        self.pr_repository_id = pr_repository_id
        self.pr_number = pr_number
        self.params = params or {}
        self.created_at = dt.now()
        self.updated_at = dt.now()

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
        repository = data.get("repository")

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
