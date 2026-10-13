"""
Projects, the top of the ownership chain.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import Models, sqla_column


class Project(db.Model, BaseModel):
    __tablename__ = 'projects'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String(256), unique=True, nullable=False)
    description = sa.Column(sa.String(4096), nullable=True)
    # Sensors only act on the repositories of enabled projects.
    enabled = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    default_dataset_id = sa.Column(
        sa.Integer,
        sa.ForeignKey('datasets.id', ondelete='SET NULL', use_alter=True,
                      name='fk_projects_default_dataset'),
        nullable=True,
    )
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    datasets = relationship(
        "Dataset", back_populates="project", foreign_keys="Dataset.project_id"
    )
    # post_update: projects and datasets reference each other, so this column is set in
    # its own UPDATE rather than by the unit of work ordering the two tables.
    default_dataset = relationship("Dataset", foreign_keys=[default_dataset_id], post_update=True)
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

    def get_results_repository(self):
        """
        The project's results repository, or None. One per project for now: the only place
        that assumes it.
        """
        return self.results_repositories[0] if self.results_repositories else None

    def resolve_dataset(self, name: str | None):
        """
        The dataset a task in this project runs against: the one named, which has to belong
        to the project, otherwise the project's default. A task may have none.
        """
        if name:
            dataset = Models.Dataset.query.filter(
                Models.Dataset.project_id == self.id, Models.Dataset.name == name.lower()
            ).one_or_none()
            if dataset is None:
                raise InvalidRequest(f"Dataset {name} does not belong to project {self.name}")
            return dataset
        return self.default_dataset

    def __repr__(self):
        return f'<Project {self.name}>'
