"""Results repository model for task output storage, global: projects are assigned to it."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column
from app.models.git_repository import GitRepositoryMixin


class ResultsRepository(GitRepositoryMixin, db.Model, BaseModel):
    __tablename__ = 'results_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.UniqueConstraint('uri', name='uq_results_repositories_uri'),
    )

    project_assignments = relationship("ProjectResultsRepository", back_populates="results_repository")
    secret = relationship(
        "Secret", back_populates="results_repositories"
    )

    def __init__(
        self,
        uri: str,
        provider: str,
        api_uri: str,
        secret_id: int,
    ):
        self.uri = uri
        self.provider = provider
        self.api_uri = api_uri
        self.secret_id = secret_id

    def __repr__(self):
        return f'<ResultsRepository ({self.uri})>'
