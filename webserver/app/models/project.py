"""
Projects, the top of the ownership chain.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import Models, sqla_column
from app.models.result_state import ResultState
from app.models.task_status import TaskStatus


class Project(db.Model, BaseModel):
    __tablename__ = 'projects'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String(256), unique=True, nullable=False)
    description = sa.Column(sa.String(4096), nullable=True)
    # Sensors only act on the repositories of enabled projects.
    enabled = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    # While locked, ingest and evaluation skip the project and API tasks are rejected, so
    # its configuration can change once what is in flight has drained.
    locked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    # Tied to the project's own assignment by the composite foreign key below, so a default
    # can only be a dataset the project has been assigned.
    default_dataset_id = sa.Column(sa.Integer, nullable=True)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        # use_alter: project_datasets references projects too, so this constraint is added
        # once both tables exist. Nothing is written to the column by the unit of work.
        sa.ForeignKeyConstraint(
            ['id', 'default_dataset_id'], ['project_datasets.project_id', 'project_datasets.dataset_id'],
            name='fk_projects_default_dataset', use_alter=True
        ),
    )

    dataset_assignments = relationship(
        "ProjectDataset", back_populates="project", foreign_keys="ProjectDataset.project_id"
    )
    trigger_repositories = relationship("TriggerRepository", back_populates="project")
    # The foreign keys of these three are ON DELETE CASCADE, so the database removes the
    # rows and the ORM must neither select them nor null their NOT NULL project_id.
    whitelisted_images = relationship(
        "WhitelistedImage", back_populates="project", cascade="all, delete", passive_deletes=True
    )
    results_repositories = relationship("ResultsRepository", back_populates="project")
    results_backend = relationship(
        "ResultsBackend", back_populates="project", uselist=False,
        cascade="all, delete", passive_deletes=True
    )
    triggers = relationship(
        "Trigger", back_populates="project", cascade="all, delete", passive_deletes=True
    )

    def __init__(self, name: str, description: str | None = None, enabled: bool = False, **kwargs):
        self.name = name
        self.description = description
        self.enabled = enabled

    def in_flight_task_ids(self) -> list[int]:
        """
        The ids of the project's tasks that are still in flight: pending, queued or running,
        succeeded with no result yet, or with a result being delivered.
        """
        Task, Result, PullRequestResult = Models.Task, Models.Result, Models.PullRequestResult
        running = [TaskStatus.PENDING.value, TaskStatus.QUEUED.value, TaskStatus.RUNNING.value]
        undelivered = sa.exists().where(
            PullRequestResult.task_id == Task.id, PullRequestResult.state == ResultState.IN_PROGRESS.value
        )
        no_result = ~sa.exists().where(Result.task_id == Task.id)
        tasks = Task.query.filter(
            Task.project_id == self.id,
            sa.or_(
                Task.status.in_(running),
                sa.and_(Task.status == TaskStatus.SUCCESS.value, no_result),
                undelivered,
            ),
        ).order_by(Task.id)
        return [t.id for t in tasks]

    def get_results_repository(self):
        """
        The project's results repository, or None. One per project for now: the only place
        that assumes it.
        """
        return self.results_repositories[0] if self.results_repositories else None

    @property
    def datasets(self) -> list:
        """The datasets assigned to the project, active or not."""
        return [assignment.dataset for assignment in self.dataset_assignments]

    @property
    def default_dataset(self):
        return None if self.default_dataset_id is None else db.session.get(
            Models.Dataset, self.default_dataset_id
        )

    def resolve_dataset(self, name: str | None):
        """
        The dataset a task in this project runs against: the one named, which the project has
        to be assigned and active, otherwise the project's default, which has to be active
        too. A task may have none.
        """
        if name:
            assignment = Models.ProjectDataset.query.join(Models.Dataset).filter(
                Models.ProjectDataset.project_id == self.id, Models.Dataset.name == name.lower()
            ).one_or_none()
            if assignment is None:
                raise InvalidRequest(f"Dataset {name} does not belong to project {self.name}")
        elif self.default_dataset_id is None:
            return None
        else:
            assignment = Models.ProjectDataset.query.filter_by(
                project_id=self.id, dataset_id=self.default_dataset_id
            ).one()
        if not assignment.active:
            raise InvalidRequest(f"Dataset {assignment.dataset.name} is not active in project {self.name}")
        return assignment.dataset

    def __repr__(self):
        return f'<Project {self.name}>'
