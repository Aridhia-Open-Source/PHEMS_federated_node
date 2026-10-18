"""Results repository model for task output storage, global: projects are assigned to it."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.soft_delete import SoftDeleteMixin
from app.models import sqla_column
from app.models.git_repository import GitRepositoryMixin


class ResultsRepository(SoftDeleteMixin, GitRepositoryMixin, db.Model, BaseModel):
    __tablename__ = 'results_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    # Turned on or off for the whole node, whatever the projects' links say
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.Index(
            'uq_results_repositories_provider_repo_path', 'provider_id', 'repo_path',
            unique=True, postgresql_where=sa.text('deleted_at IS NULL')
        ),
    )

    project_assignments = relationship("ProjectResultsRepository", back_populates="results_repository")
    provider = relationship("GitProvider", back_populates="results_repositories")
    secret = relationship(
        "Secret", back_populates="results_repositories"
    )

    def __init__(
        self,
        provider_id: int,
        repo_path: str,
        secret_id: int,
        enabled: bool = True,
    ):
        self.provider_id = provider_id
        self.repo_path = repo_path
        self.secret_id = secret_id
        self.enabled = enabled

    def __repr__(self):
        return f'<ResultsRepository ({self.uri})>'
