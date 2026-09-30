"""Delivery of one task's results to one results repository."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column
from app.models.task_result_status import TaskResultStatus


class TaskResult(db.Model, BaseModel):
    """One row per (task, destination)."""
    __tablename__ = 'task_results'
    __table_args__ = (
        sa.UniqueConstraint('task_id', 'results_repository_id', name='uq_task_results_task_repository'),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    task_id = sa.Column(sa.Integer, sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False)
    results_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('results_repositories.id', ondelete='RESTRICT'), nullable=False
    )
    status = sa.Column(
        sa.String(32),
        nullable=False,
        default=TaskResultStatus.PENDING.value,
        server_default=TaskResultStatus.PENDING.value,
    )
    attempts = sa.Column(sa.Integer, nullable=False, default=0, server_default='0')
    branch = sa.Column(sa.String(256), nullable=True)
    commit_sha = sa.Column(sa.String(40), nullable=True)
    pull_request_number = sa.Column(sa.Integer, nullable=True)
    pull_request_url = sa.Column(sa.String(4096), nullable=True)
    error = sa.Column(sa.String(1024), nullable=True)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    task = relationship("Task", back_populates="results")
    results_repository = relationship("ResultsRepository", back_populates="task_results")
