"""
Projects, the top of the ownership chain.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column


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
    default_dataset = relationship("Dataset", foreign_keys=[default_dataset_id])
    requests = relationship("Request", back_populates="project")
    trigger_repositories = relationship("TriggerRepository", back_populates="project")
    whitelisted_images = relationship("WhitelistedImage", back_populates="project")
    results_repositories = relationship("ResultsRepository", back_populates="project")
    results_backend = relationship("ResultsBackend", back_populates="project", uselist=False)
    api_requests = relationship("ApiRequest", back_populates="project")
    task_requests = relationship("TaskRequest", back_populates="project")

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

    def __repr__(self):
        return f'<Project {self.name}>'
