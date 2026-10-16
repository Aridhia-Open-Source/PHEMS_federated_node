"""
A pull request merged to a global trigger repository: the provider's facts, stored once however
many projects watch the repository. What a project makes of it (state, spec, task) is its
`PullRequestTrigger`.
"""
from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import validates

from app.helpers.base_model import BaseModel, db


class PullRequest(db.Model, BaseModel):
    __tablename__ = 'pull_requests'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    trigger_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('trigger_repositories.id', ondelete='CASCADE'), nullable=False
    )
    number = sa.Column(sa.Integer, nullable=False)
    title = sa.Column(sa.String(256), nullable=False)
    raised_by = sa.Column(sa.String(256), nullable=False)
    merge_commit_sha = sa.Column(sa.String(40), nullable=False)
    merged_at = sa.Column(sa.DateTime(timezone=False), nullable=False)
    # The branch the pull request was merged into
    base_branch = sa.Column(sa.String(256), nullable=False)
    # The provider caps the changed files it lists. Past the cap the list is incomplete, so the
    # pull request is taken to touch every path.
    files_truncated = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.UniqueConstraint('trigger_repository_id', 'number', name='uq_pull_requests_repo_number'),
        sa.Index('ix_pull_requests_repo_merged_at_number', 'trigger_repository_id', 'merged_at', 'number'),
    )

    files = orm.relationship(
        "PullRequestFile", back_populates="pull_request", cascade="all, delete-orphan", passive_deletes=True
    )

    @validates('merged_at')
    def validate_merged_at(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                return dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("merged_at must be a valid ISO 8601 datetime string")
        return value

    def __repr__(self):
        return f'<PullRequest (repository_id={self.trigger_repository_id}, pr={self.number})>'


class PullRequestFile(db.Model, BaseModel):
    """
    A file a pull request changed: its path and how (`added`, `modified`...). Only the path
    and status are kept, never content. The status is kept because a spec is a file the pull
    request adds.
    """
    __tablename__ = 'pull_request_files'

    pull_request_id = sa.Column(
        sa.Integer, sa.ForeignKey('pull_requests.id', ondelete='CASCADE'), primary_key=True
    )
    path = sa.Column(sa.String(1024), primary_key=True)
    status = sa.Column(sa.String(32), nullable=False)

    pull_request = orm.relationship("PullRequest", back_populates="files")
