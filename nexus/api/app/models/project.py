"""
Projects, the top of the ownership chain.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.helpers.soft_delete import SoftDeleteMixin
from app.models import Models, sqla_column


class Project(SoftDeleteMixin, db.Model, BaseModel):
    __tablename__ = 'projects'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String(256), nullable=False)
    description = sa.Column(sa.String(4096), nullable=True)
    # Sensors only act on the repositories of enabled projects. While a project is disabled it
    # gets no new triggers and API tasks are rejected; its PENDING tasks wait.
    enabled = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    # The controller withdrew the project: everything it uses is blocked, its tasks fail and nothing is
    # delivered. Never touches enabled, so a re-grant restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    # A dataset the project has been assigned: set with the first one linked.
    default_dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='RESTRICT'), nullable=True)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.Index('uq_projects_name', 'name', unique=True, postgresql_where=sa.text('deleted_at IS NULL')),
    )

    dataset_assignments = relationship(
        "ProjectDataset", back_populates="project", foreign_keys="ProjectDataset.project_id"
    )
    trigger_repository_assignments = relationship("ProjectTriggerRepository", back_populates="project")
    secret_assignments = relationship("ProjectSecret", back_populates="project")
    # The foreign keys of these three are ON DELETE CASCADE, so the database removes the
    # rows and the ORM must neither select them nor null their NOT NULL project_id.
    results_repository_assignments = relationship("ProjectResultsRepository", back_populates="project")
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

    def get_results_repository(self):
        """
        The project's assignment of a results repository, active or not, or None. One per
        project for now: the only place that assumes it.
        """
        return self.results_repository_assignments[0] if self.results_repository_assignments else None

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
