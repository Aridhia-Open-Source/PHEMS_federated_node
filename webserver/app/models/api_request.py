"""API request model for task trigger payloads."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column


class ApiRequest(db.Model, BaseModel):
    __tablename__ = 'api_requests'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    user_id = sa.Column(sa.String(256), nullable=False)
    payload = sa.Column(sa.JSON, nullable=False, default=dict, server_default='{}')
    created_at = sqla_column.created_at()

    project = relationship('Project', back_populates='api_requests')
    tasks = relationship('Task', back_populates='api_request')

    def __init__(self, user_id: str, project_id: int, payload: dict | None = None, **kwargs):
        self.user_id = user_id
        self.project_id = project_id
        self.payload = payload or {}

    def __repr__(self):
        return f'<ApiRequest (id={self.id}, project_id={self.project_id})>'
