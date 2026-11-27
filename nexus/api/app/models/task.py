import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.dtos.repository_uri import RepositoryUriRequest
from app.database.base_model import BaseModel, db
from fednode.clients.git.uri import normalise_repo_uri
from app.clients.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest
from app.models import Models, sqla_column
from app.models.task_spec import TaskSpec
from app.models.task_status import TaskStatus


logger = logging.getLogger('task_model')
logger.setLevel(logging.INFO)

SNAPSHOT_VERSION = 1


@dataclass
class LaunchDecision:
    """
    What to do with a PENDING task: outcome "launch" or "fail" (a cause comes with "fail"). revoked and
    changes are the facts the rules read, kept so a caller can show them.
    """
    outcome: str
    cause: str | None = None
    revoked: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


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
    # The configuration the task is pinned to and its hash, see Task.snapshot. Null on
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
    def validate(cls, data:dict, user_token:str):
        data["name"] = (data.get("name") or "").replace(" ", "")
        if not data["name"]:
            raise InvalidRequest("name is a mandatory field")

        kc_client = Keycloak()
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
        cls.validate_image_format(data["docker_image"])

        return data

    @classmethod
    def validate_image_format(cls, image: str):
        tag_ok = re.match(r'^\w[\w\.\-/]+\w:[\w\.\-]+$', image)
        sha_ok = re.match(r'^\w[\w\.\-/]+\w@(sha256:)?[a-fA-F0-9]{7,64}$', image)
        if not (tag_ok or sha_ok):
            raise InvalidRequest(
                f"{image} does not have a tag or is malformed. Please provide one in "
                "the format <registry>/<image>:<tag> or <registry>/<image>@sha256.."
            )

    # The configuration a task is pinned to. When a task is created a small snapshot of what decides
    # where its results go and which data it reads is stored on it, with a hash. Before the task
    # launches and before its results are published the snapshot is rebuilt from the current state
    # and compared: a task whose setup changed fails and is never run or published against the new one.
    #
    # Not in the snapshot: credentials and secrets (a rotation has to reach running work), the trigger
    # repository (the task is pinned to the pull request's merge sha) and the enabled and revoked flags
    # (those have their own rules). One of those is shared: a task whose project, or a trigger, dataset or
    # results repository it uses (the project resource, the global resource, a repository's provider) is
    # revoked or deleted (see revoked_resources) does not launch and its results are never delivered.

    @staticmethod
    def snapshot(project, dataset) -> dict:
        """
        The snapshot of the configuration a task of the project, running on the dataset (or none), is
        built against. The project has at most one results resource.
        """
        resource = project.get_results_repository()
        results = None
        if resource is not None:
            repository = resource.results_repository
            results = {
                "repository_id": repository.id,
                "repository": repository.uri,
                "api_uri": repository.provider.api_uri,
                "target_dir": resource.target_dir,
                "base_branch": resource.base_branch,
            }
        return {
            "version": SNAPSHOT_VERSION,
            "results": results,
            "dataset": None if dataset is None else {
                "name": dataset.name,
                "host": dataset.host,
                "port": dataset.port,
                "type": dataset.type,
                "read_schema": dataset.read_schema,
                "write_schema": dataset.write_schema,
            },
        }

    @staticmethod
    def snapshot_hash(snapshot: dict) -> str:
        """sha256 hex of the snapshot's canonical JSON."""
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _diff_value(path: str, stored, current, changes: list[str]):
        if isinstance(stored, dict) and isinstance(current, dict):
            # Only what the stored snapshot has is compared: a field added later is unchanged
            for key in stored:
                Task._diff_value(f"{path}.{key}", stored[key], current.get(key), changes)
        elif stored != current:
            changes.append(f"{path}: {stored!r} -> {current!r}")

    @staticmethod
    def diff(stored: dict, current: dict) -> list[str]:
        """
        Human-readable lines for what differs, e.g. "results.target_dir: 'results/' -> 'out/'". Only
        keys present in the stored snapshot are compared, and a differing version is not a change.
        """
        changes: list[str] = []
        for key in stored:
            if key == "version":
                continue
            Task._diff_value(key, stored[key], current.get(key), changes)
        return changes

    def config_changes(self) -> list[str]:
        """What changed in the task's configuration since it was created. Empty when it has no snapshot."""
        if not self.config_snapshot:
            return []
        return self.diff(self.config_snapshot, self.snapshot(self.project, self.spec.dataset))

    def revoked_resources(self, results_repository_id: int | None = None) -> list[str]:
        """
        What the task uses that is revoked or deleted; empty when nothing is. A task with a revoked resource does
        not launch and its results are never delivered. Switched off is not revoked. Each is named once:
        - the project the task is in: "project p (revoked)";
        - the pull request trigger's repository: its project resource, "trigger repository o/r", the global repository
          and its provider, "trigger repository o/r (revoked)", "provider git (revoked)";
        - the dataset: its project resource, "dataset ds" (also when the project has none), the global dataset,
          "dataset ds (revoked)";
        - the results repository, like the trigger one. Its project resource is for the given repository, else the one
          the task was pinned to, else the project's newest.
        """
        revoked = []

        def add(name: str):
            if name not in revoked:
                revoked.append(name)

        def add_repository(kind: str, resource, repository):
            if resource.revoked:
                add(f"{kind} {repository.repo_path}")
            if repository.revoked:
                add(f"{kind} {repository.repo_path} (revoked)")
            if repository.provider.revoked:
                add(f"provider {repository.provider.name} (revoked)")

        if self.project.revoked:
            add(f"project {self.project.name} (revoked)")
        if isinstance(self.trigger, Models.PullRequestTrigger):
            resource = self.trigger.project_trigger_repository
            add_repository("trigger repository", resource, resource.trigger_repository)
        if self.spec.dataset_id:
            resource = Models.ProjectDataset.query.filter_by(
                project_id=self.project_id, dataset_id=self.spec.dataset_id
            ).execution_options(include_deleted=True).order_by(Models.ProjectDataset.id.desc()).first()
            if resource is None or resource.revoked:
                add(f"dataset {self.spec.dataset.name}")
            if self.spec.dataset.revoked:
                add(f"dataset {self.spec.dataset.name} (revoked)")
        if results_repository_id is None and self.config_snapshot and self.config_snapshot["results"]:
            results_repository_id = self.config_snapshot["results"]["repository_id"]
        resource = Models.ProjectResultsRepository.latest(self.project_id, results_repository_id)
        if resource is not None:
            add_repository("results repository", resource, resource.results_repository)
        return revoked

    def decide_launch(self) -> LaunchDecision:
        """
        The one place the rules for launching a task live. Read-only, so a caller can ask every tick. The first
        rule that applies decides, in this order, and its cause is what the task records:
        1. something the task uses is revoked or deleted: "revoked: <names joined by '; '>" (see revoked_resources);
        2. its pinned configuration changed: "task configuration changed since the task was created: <changes joined by '; '>";
        3. its dataset's project resource is not active (project resource or global dataset switched off, revoked or deleted):
           "Dataset <name> is not active in project <project>";
        4. its dataset's secret is disabled: "The secret of dataset <name> is disabled".
        Otherwise it is "launch". A task without a dataset skips rules 3 and 4. The cause is not truncated: its column
        length is the writer's concern.
        """
        revoked = self.revoked_resources()
        changes = self.config_changes()
        if revoked:
            return LaunchDecision("fail", "revoked: " + "; ".join(revoked), revoked, changes)
        if changes:
            cause = "task configuration changed since the task was created: " + "; ".join(changes)
            return LaunchDecision("fail", cause, revoked, changes)
        dataset = self.spec.dataset if self.spec.dataset_id else None
        if dataset is not None:
            resource = Models.ProjectDataset.query.filter_by(project_id=self.project_id, dataset_id=dataset.id).first()
            if resource is None or not resource.active:
                cause = f"Dataset {dataset.name} is not active in project {self.project.name}"
                return LaunchDecision("fail", cause, revoked, changes)
            if not dataset.secret.enabled:
                return LaunchDecision("fail", f"The secret of dataset {dataset.name} is disabled", revoked, changes)
        return LaunchDecision("launch", None, revoked, changes)
