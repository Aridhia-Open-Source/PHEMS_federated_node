import logging
from datetime import datetime as dt
from http import HTTPStatus

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.dtos.repository_uri import RepositoryUriRequest
from app.helpers.compute import validate_cpu_resources, validate_memory_resources
from app.helpers.const import ENABLE_IMAGE_WHITELIST
from app.helpers.base_model import BaseModel, db
from app.helpers.git_uri import normalise_repo_uri
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest, NotImplementedException, TaskImageException
from app.models import Models, sqla_column
from app.models.task_spec import TaskSpec
from app.models.task_status import TaskStatus


logger = logging.getLogger('task_model')
logger.setLevel(logging.INFO)


class Task(db.Model, BaseModel):
    __tablename__ = 'tasks'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False, index=True
    )
    trigger_id = sa.Column(
        sa.Integer, sa.ForeignKey('triggers.id', ondelete='RESTRICT'), nullable=False, unique=True
    )
    task_spec_id = sa.Column(sa.Integer, sa.ForeignKey('task_specs.id', ondelete='RESTRICT'), nullable=False)

    name = sa.Column(sa.String(256), nullable=False)
    status = sa.Column(sa.String(256), default=TaskStatus.PENDING.value)
    # The run's attempt number. A retry is the same task with the next attempt.
    attempt = sa.Column(sa.Integer, nullable=False, default=1, server_default='1')
    requested_by = sa.Column(sa.String(256), nullable=False)
    executor_run_id = sa.Column(sa.String(64), nullable=True, unique=True)
    exit_code = sa.Column(sa.Integer, nullable=True)
    # Why the task failed without a run, e.g. its dataset was revoked before launch
    state_cause = sa.Column(sa.Text, nullable=True)
    # The configuration the task is pinned to and its hash, see helpers/task_config. Null on
    # tasks created before it existed, which are never reported as changed.
    config_snapshot = sa.Column(sa.JSON, nullable=True)
    config_hash = sa.Column(sa.String(64), nullable=True)

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()
    started_at = sa.Column(sa.DateTime(timezone=False), nullable=True)
    completed_at = sa.Column(sa.DateTime(timezone=False), nullable=True)

    params = sa.Column(sa.JSON, nullable=False, server_default='{}')

    # The spec is the task's own: it goes when the task does
    spec = relationship("TaskSpec", cascade="all, delete-orphan", single_parent=True)
    project = relationship("Project")
    trigger = relationship("Trigger", back_populates="task")
    results = relationship("Result", back_populates="task", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        sa.Index('ix_tasks_requested_by', 'requested_by'),
        sa.Index('ix_tasks_status_project', 'status', 'project_id'),
    )

    def __init__(self,
                 name:str,
                 requested_by:str,
                 project_id:int,
                 trigger_id:int,
                 spec:dict,
                 params:dict | None = None,
                 config_snapshot:dict | None = None,
                 config_hash:str | None = None,
                 ):
        self.name = name
        self.status = TaskStatus.PENDING.value
        self.requested_by = requested_by
        self.project_id = project_id
        self.attempt = 1
        self.trigger_id = trigger_id
        self.spec = TaskSpec(**spec)
        self.params = params or {}
        self.config_snapshot = config_snapshot
        self.config_hash = config_hash
        self.created_at = dt.now()
        self.updated_at = dt.now()

    @property
    def project_name(self) -> str:
        return self.project.name

    @property
    def dataset_name(self) -> str | None:
        """The name of the dataset the task actually uses, the one its spec resolved to."""
        return self.spec.dataset.name if self.spec.dataset else None

    @classmethod
    def _get_required_fields(cls) -> list[str]:
        # Set when the task is created from its validated trigger, never in a request body
        return [f for f in super()._get_required_fields() if f not in ("trigger_id", "task_spec_id")]

    @classmethod
    def validate(cls, data:dict):
        data["name"] = (data.get("name") or "").replace(" ", "")
        if not data["name"]:
            raise InvalidRequest("name is a mandatory field")

        kc_client = Keycloak()
        user_token = Keycloak.get_token_from_headers()

        decoded_token = kc_client.decode_token(user_token)
        data["requested_by"] = kc_client.get_user_by_email(decoded_token["email"])["id"]
        repository = data.get("repository")

        data = super().validate(data)

        # A task always states which project it belongs to. Delivery and the image
        # allow-list are both scoped to it, so neither resolves without one.
        repo = None
        if repository:
            uri = RepositoryUriRequest.normalised(repository)
            assignments = [
                a for a in Models.ProjectTriggerRepository.query.join(Models.TriggerRepository).filter(
                    Models.TriggerRepository.repo_path == "/".join(uri.split("/")[-2:])
                ) if normalise_repo_uri(a.trigger_repository.uri) == uri
            ]
            if not assignments:
                raise InvalidRequest(f"No datasets assigned with the repository {repository}")
            if len(assignments) > 1:
                raise InvalidRequest(f"The repository {repository} is assigned to several projects")
            # The sensor sends no project, so a PR-driven task takes its repository's.
            project = assignments[0].project
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

        # The named dataset if the spec has one, otherwise the project's default. Either has
        # to be an active assignment of the project. A task may have none.
        # TODO(DAR): DAR checking is disconnected for now. A non-admin caller used to need
        # an active DAR covering the dataset, now they take the same path as admins and
        # repositories. Revisit with the authorization rework.
        data["dataset"] = project.resolve_dataset(requested_ds.name if requested_ds else None)

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
            validate_cpu_resources(
                data["resources"].get("limits", {}).get("cpu"),
                data["resources"].get("requests", {}).get("cpu")
            )
            validate_memory_resources(
                data["resources"].get("limits", {}).get("memory"),
                data["resources"].get("requests", {}).get("memory")
            )
        return data

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
