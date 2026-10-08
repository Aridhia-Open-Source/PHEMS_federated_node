from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import validates

from app.models.trigger import Trigger


class PullRequestTrigger(Trigger):
    """
    A pull request merged to a watched repository, the trigger of a task. Only merged pull
    requests are watched.
    Not to be confused with `PullRequestResult`, the pull request we open to deliver results.
    Stores PR metadata and payload (the raw spec) for async processing by Dagster.
    `state`, `state_cause` and `project_id` are columns of the Trigger it extends.
    """
    __tablename__ = 'pull_request_triggers'
    __mapper_args__ = {'polymorphic_identity': 'PR'}
    __table_args__ = (
        sa.UniqueConstraint('trigger_repository_id', 'number', name='uq_pr_repo_number'),
    )

    trigger_id = sa.Column(
        sa.Integer, sa.ForeignKey('triggers.id', ondelete='CASCADE'), primary_key=True
    )
    number = sa.Column(sa.Integer, nullable=False)
    title = sa.Column(sa.String(256), nullable=False)
    raised_by = sa.Column(sa.String(256), nullable=False)
    merge_commit_sha = sa.Column(sa.String(40), nullable=False)
    merged_at = sa.Column(sa.DateTime(timezone=False), nullable=False)
    payload = sa.Column(sa.JSON, nullable=False, default={})

    trigger_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('trigger_repositories.id', ondelete='CASCADE'),
        nullable=False
    )

    trigger_repository = orm.relationship("TriggerRepository", back_populates="pull_request_triggers")

    @validates('merged_at')
    def validate_merged_at(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                return dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("merged_at must be a valid ISO 8601 datetime string")
        return value

    def __init__(
        self,
        project_id: int,
        trigger_repository_id: int,
        number: int,
        title: str,
        raised_by: str,
        merged_at: dt,
        merge_commit_sha: str,
        payload: dict | None = None,
    ):
        super().__init__(project_id)
        self.trigger_repository_id = trigger_repository_id
        self.number = number
        self.title = title
        self.raised_by = raised_by
        self.merged_at = merged_at
        self.payload = payload or {}
        self.merge_commit_sha = merge_commit_sha

    @property
    def requested_by(self) -> str:
        return self.raised_by

    def __repr__(self):
        return f'<PullRequestTrigger (repo_id={self.trigger_repository_id}, pr={self.number})>'
