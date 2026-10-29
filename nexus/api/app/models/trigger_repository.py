"""Trigger repository model, global: projects are assigned to it."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.helpers.soft_delete import SoftDeleteMixin
from app.models import Models, sqla_column
from app.models.git_repository import GitRepositoryMixin


class TriggerRepository(SoftDeleteMixin, GitRepositoryMixin, db.Model, BaseModel):
    __tablename__ = 'trigger_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    # Turned on or off for the whole node, whatever the project resources say
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # The controller withdrew the repository from the whole node: every project's use of it is blocked.
    # Never touches enabled, so a re-grant restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.Index(
            'uq_trigger_repositories_provider_repo_path', 'provider_id', 'repo_path',
            unique=True, postgresql_where=sa.text('deleted_at IS NULL')
        ),
    )

    project_assignments = relationship("ProjectTriggerRepository", back_populates="trigger_repository")
    provider = relationship("GitProvider", back_populates="trigger_repositories")
    secret = relationship(
        "Secret", back_populates="trigger_repositories"
    )

    def get_pull_request_cursor(self) -> str | None:
        """The latest merge among the stored pull requests, None when there are none."""
        merged_at = db.session.query(func.max(Models.PullRequest.merged_at))\
            .filter_by(trigger_repository_id=self.id)\
            .scalar()
        return merged_at.strftime("%Y-%m-%dT%H:%M:%SZ") if merged_at else None

    def get_ingest_cursor(self) -> str:
        """
        Where polling the provider resumes: the latest stored merge, or, with no pull request
        stored yet, the repository's creation.
        """
        return self.get_pull_request_cursor() or self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")

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
        return f'<TriggerRepository ({self.uri})>'
