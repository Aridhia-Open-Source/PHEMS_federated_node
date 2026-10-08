"""Delivery of one task's results to one results repository."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column


class Result(db.Model, BaseModel):
    """
    One row per (task, destination). Each way of delivering is a child table sharing
    this id, picked by `type`, and the child holds the state of its delivery.
    """
    __tablename__ = 'results'
    __mapper_args__ = {'polymorphic_on': 'type'}
    __table_args__ = (
        sa.UniqueConstraint('task_id', 'results_repository_id', name='uq_results_task_repository'),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    type = sa.Column(sa.String(16), nullable=False)
    task_id = sa.Column(sa.Integer, sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False)
    results_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('results_repositories.id', ondelete='RESTRICT'), nullable=False
    )
    # How many times the delivery ran to its end, failed or not. Bumped by Dagster.
    attempts = sa.Column(sa.Integer, nullable=False, default=0, server_default='0')
    # Why the last attempt failed, cleared when one succeeds. The state is left where it was.
    error = sa.Column(sa.String(1024), nullable=True)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    task = relationship("Task", back_populates="results")
    results_repository = relationship("ResultsRepository", back_populates="results")
