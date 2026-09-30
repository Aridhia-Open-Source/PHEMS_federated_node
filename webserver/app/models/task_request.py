from sqlalchemy.orm import relationship
import sqlalchemy as sa

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidDBEntry
from app.models import sqla_column


class TaskRequest(db.Model, BaseModel):
    """
    A request to run a task, from a pull request or an API call, holding the normalised TaskSpec.

    `queued`: True means the request is waiting to be launched. The launcher sets it False
    once a run has been started.
    """
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

    __table_args__ = (
        sa.CheckConstraint(
            '(pull_request_id IS NULL) <> (api_request_id IS NULL)',
            name='ck_task_requests_one_source',
        ),
    )

    def __init__(self, project_id: int, payload: dict,
                 pull_request_id: int | None = None, api_request_id: int | None = None,
                 queued: bool = False):
        if (pull_request_id is None) == (api_request_id is None):
            raise InvalidDBEntry("A task request needs exactly one of pull_request_id and api_request_id")
        self.project_id = project_id
        self.payload = payload
        self.pull_request_id = pull_request_id
        self.api_request_id = api_request_id
        self.queued = queued
