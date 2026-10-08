from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import validates

from app.models.task_result import TaskResult


class PullRequestResult(TaskResult):
    """
    A pull request we open on a results repository to deliver a task's results.
    Not to be confused with the trigger-side `PullRequest`, the merged pull request we watch
    that leads to a task.
    Columns are filled in stages as the delivery progresses: branch and commit when pushed,
    the pull request once opened, and its state, merge time and sha as it is synced.
    """
    __tablename__ = 'pull_request_results'
    __mapper_args__ = {'polymorphic_identity': 'PR'}

    task_result_id = sa.Column(
        sa.Integer, sa.ForeignKey('task_results.id', ondelete='CASCADE'), primary_key=True
    )
    branch = sa.Column(sa.String(256), nullable=True)
    commit_sha = sa.Column(sa.String(40), nullable=True)
    number = sa.Column(sa.Integer, nullable=True)
    url = sa.Column(sa.String(4096), nullable=True)
    merge_status = sa.Column(sa.String(16), nullable=True)
    merged_at = sa.Column(sa.DateTime(timezone=False), nullable=True)
    merge_commit_sha = sa.Column(sa.String(40), nullable=True)

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
        return f'<PullRequestResult (task_id={self.task_id}, pr={self.number})>'
