"""Results repository model for task output storage."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column
from app.models.git_repository import GitRepositoryMixin


class ResultsRepository(GitRepositoryMixin, db.Model, BaseModel):
    __tablename__ = 'results_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    target_dir = sa.Column(sa.String(4096), nullable=False)
    owned_by_federated_node = sa.Column(sa.Boolean, nullable=False, server_default='true')
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        # One results repository per project for now.
        sa.UniqueConstraint('project_id', name='uq_results_repositories_project'),
        sa.UniqueConstraint('project_id', 'uri', name='uq_results_repositories_project_uri'),
        sa.ForeignKeyConstraint(
            ['project_id', 'secret_id'], ['secrets.project_id', 'secrets.id'],
            ondelete='RESTRICT'
        ),
    )

    project = relationship("Project", back_populates="results_repositories")
    secret = relationship(
        "Secret", back_populates="results_repositories",
        overlaps="results_repositories,project,trigger_repositories,datasets"
    )

    def __init__(
        self,
        uri: str,
        provider: str,
        api_uri: str,
        secret_id: int,
        target_dir: str,
        project_id: int,
        owned_by_federated_node: bool = True,
    ):
        self.uri = uri
        self.provider = provider
        self.api_uri = api_uri
        self.secret_id = secret_id
        self.target_dir = target_dir
        self.project_id = project_id
        self.owned_by_federated_node = owned_by_federated_node

    def __repr__(self):
        return f'<ResultsRepository ({self.uri})>'
