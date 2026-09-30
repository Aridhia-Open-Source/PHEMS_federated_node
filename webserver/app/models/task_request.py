from sqlalchemy.orm import relationship
import sqlalchemy as sa

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column


class TaskRequest(db.Model, BaseModel):
    __tablename__ = 'task_requests'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    pull_request_id = sa.Column(
        sa.Integer, sa.ForeignKey('pull_requests.id', ondelete='CASCADE'), nullable=True
    )
    api_request_id = sa.Column(
        sa.Integer, sa.ForeignKey('api_requests.id', ondelete='CASCADE'), nullable=True
    )
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )
    queued = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())
    payload = sa.Column(sa.JSON, nullable=False, default=dict)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    pull_request = relationship('PullRequest', back_populates='task_request')
    api_request = relationship('ApiRequest', back_populates='task_request')
    project = relationship('Project', back_populates='task_requests')
    task = relationship('Task', back_populates='task_request', uselist=False)
