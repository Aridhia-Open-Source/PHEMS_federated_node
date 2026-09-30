from datetime import datetime as dt
from datetime import timezone as tz
from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.models import Models, sqla_column
from app.models.git_repository import GitRepositoryMixin


def now_ts():
    return dt.now(tz=tz.utc)


class TriggerRepository(GitRepositoryMixin, db.Model, BaseModel):
    __tablename__ = 'trigger_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    watch_dir = sa.Column(sa.String(4096), nullable=False)
    base_branch = sa.Column(sa.String(256), nullable=False, default='main')
    initial_cursor = sa.Column(
        sa.DateTime, nullable=False, server_default=func.now(), default=now_ts
    )

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.UniqueConstraint('project_id', 'uri', name='uq_trigger_repositories_project_uri'),
        sa.ForeignKeyConstraint(
            ['project_id', 'k8s_secret_id'], ['k8s_secrets.project_id', 'k8s_secrets.id'],
            ondelete='RESTRICT'
        ),
    )

    project = relationship("Project", back_populates="trigger_repositories")
    k8s_secret = relationship(
        "K8sSecret", back_populates="trigger_repositories", overlaps="trigger_repositories,project"
    )
    pull_requests = relationship(
        "PullRequest", back_populates="trigger_repository", cascade="all, delete"
    )

    @validates('initial_cursor')
    def validate_initial_cursor(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                value = dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("initial_cursor must be a valid ISO 8601 datetime string")

        if self.id is not None and self.pull_requests:
            raise ValueError(
                "Cannot change initial_cursor while pull requests exist. "
                "Delete all pull requests first if you want to adjust the cursor."
            )

        return value

    @property
    def dataset(self):
        """
        Which dataset a PR from this repository runs against by default
        """
        return self.project.default_dataset

    def get_pull_request_cursor(self) -> str:
        """
        Get latest PR merge time from all ingested pull requests.
        If no pull requests exist, use initial_cursor as the starting point.
        """
        pr_cursor = db.session.query(func.max(Models.PullRequest.merged_at))\
            .filter_by(trigger_repository_id=self.id)\
            .scalar()

        initial_cursor = cast(dt, self.initial_cursor)

        return (pr_cursor or initial_cursor).strftime("%Y-%m-%dT%H:%M:%SZ")

    def __init__(
        self,
        uri: str,
        provider: str,
        api_uri: str,
        k8s_secret_id: int,
        watch_dir: str,
        project_id: int,
        base_branch: str = 'main',
        initial_cursor: dt | None = None,
        repo_path: str | None = None,
    ):
        self.uri = uri
        self.provider = provider
        self.api_uri = api_uri
        self.repo_path = repo_path or self.derive_repo_path(uri)
        self.k8s_secret_id = k8s_secret_id
        self.watch_dir = watch_dir
        self.project_id = project_id
        self.base_branch = base_branch
        self.initial_cursor = initial_cursor

    def __repr__(self):
        return f'<TriggerRepository ({self.uri})>'
