"""API request model for task trigger payloads."""
import sqlalchemy as sa

from app.models.trigger import Trigger


class ApiRequest(Trigger):
    """
    A task requested through POST /tasks. `payload` is the raw request body.
    """
    __tablename__ = 'api_requests'
    __mapper_args__ = {'polymorphic_identity': 'API'}

    trigger_id = sa.Column(
        sa.Integer, sa.ForeignKey('triggers.id', ondelete='CASCADE'), primary_key=True
    )
    user_id = sa.Column(sa.String(256), nullable=False)
    payload = sa.Column(sa.JSON, nullable=False, default=dict, server_default='{}')

    def __init__(self, user_id: str, project_id: int, payload: dict | None = None, **kwargs):
        super().__init__(project_id)
        self.user_id = user_id
        self.payload = payload or {}

    @property
    def requested_by(self) -> str:
        return self.user_id

    def __repr__(self):
        return f'<ApiRequest (id={self.id}, project_id={self.project_id})>'
