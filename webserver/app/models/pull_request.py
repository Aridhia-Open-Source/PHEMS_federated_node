from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.models.pull_request_status import PullRequestStatus


class PullRequest(db.Model, BaseModel):
    """
    A GitHub pull request merged to a watched repository.`
    Stores PR metadata and spec for async processing by Dagster sensors.
    """
    __tablename__ = 'pull_requests'

    repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('repositories.id', ondelete='CASCADE'),
        nullable=False, primary_key=True
    )
    number = sa.Column(sa.Integer, nullable=False, primary_key=True)
    title = sa.Column(sa.String(256), nullable=False)
    raised_by = sa.Column(sa.String(256), nullable=False)
    merged_at = sa.Column(sa.DateTime(timezone=False), nullable=False)
    saved_at = sa.Column(sa.DateTime(timezone=False), server_default=func.now())
    is_valid = sa.Column(sa.Boolean, nullable=False, default=False)
    status = sa.Column(
        sa.String(32),
        nullable=False,
        default=PullRequestStatus.UNPROCESSED.value,
    )
    merge_commit_sha = sa.Column(sa.String(40), nullable=False)
    spec = sa.Column(sa.JSON, nullable=False, default={})

    repository = orm.relationship("Repository", back_populates="pull_requests")

    def __init__(
        self,
        repository_id: int,
        number: int,
        title: str,
        raised_by: str,
        merged_at: dt,
        merge_commit_sha: str,
        is_valid: bool,
        status: str = PullRequestStatus.UNPROCESSED.value,
        spec: dict | None = None,
    ):
        self.repository_id = repository_id
        self.number = number
        self.title = title
        self.raised_by = raised_by
        self.merged_at = merged_at
        self.spec = spec or {}
        self.merge_commit_sha = merge_commit_sha
        self.is_valid = is_valid
        self.status = status

    def __repr__(self):
        return f'<PullRequest (repo_id={self.repository_id}, pr={self.number})>'
