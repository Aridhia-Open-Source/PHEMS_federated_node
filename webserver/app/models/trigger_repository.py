"""Trigger repository model, global: projects are assigned to it."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.models import Models, sqla_column
from app.models.git_repository import GitRepositoryMixin


class TriggerRepository(GitRepositoryMixin, db.Model, BaseModel):
    __tablename__ = 'trigger_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    # Turned on or off for the whole node, whatever the projects' links say
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.UniqueConstraint('provider_id', 'repo_path', name='uq_trigger_repositories_provider_repo_path'),
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

    def get_ingest_cursor(self) -> str | None:
        """
        Where polling the provider resumes: the latest stored merge, or, with no pull request
        stored yet, the earliest creation of the repository's active links of enabled projects, where
        their cursors start.
        None when there is neither.
        """
        return self.get_pull_request_cursor() or min(
            (a.initial_cursor.strftime("%Y-%m-%dT%H:%M:%SZ") for a in self.project_assignments if a.active and a.project.enabled),
            default=None
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
        return f'<TriggerRepository ({self.uri})>'
