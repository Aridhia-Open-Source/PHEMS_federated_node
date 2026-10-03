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
    results_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('results_repositories.id', ondelete='RESTRICT'), nullable=True
    )
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    datasets = relationship(
        "Dataset", back_populates="project", foreign_keys="Dataset.project_id"
    )
    default_dataset = relationship("Dataset", foreign_keys=[default_dataset_id])
    requests = relationship("Request", back_populates="project")
    trigger_repositories = relationship("TriggerRepository", back_populates="project")
    whitelisted_images = relationship("WhitelistedImage", back_populates="project")
    results_repository = relationship("ResultsRepository", back_populates="projects")
    results_backend = relationship("ResultsBackend", back_populates="project", uselist=False)
    triggers = relationship("Trigger", back_populates="project")

    def __init__(self, name: str, description: str | None = None, enabled: bool = False, **kwargs):
        self.name = name
        self.description = description
        self.enabled = enabled

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
