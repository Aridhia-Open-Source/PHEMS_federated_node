"""API request model for task triggers."""
import sqlalchemy as sa

from app.models.trigger import Trigger


class ApiRequestTrigger(Trigger):
    """
    A task requested through POST /tasks. `spec_raw` is the raw request body.
    """
    __tablename__ = 'api_request_triggers'
    __mapper_args__ = {'polymorphic_identity': 'API'}

    trigger_id = sa.Column(
        sa.Integer, sa.ForeignKey('triggers.id', ondelete='CASCADE'), primary_key=True
    )
    user_id = sa.Column(sa.String(256), nullable=False)
    spec_raw = sa.Column(sa.Text, nullable=True)

    def __init__(self, user_id: str, project_id: int, **kwargs):
        super().__init__(project_id)
        self.user_id = user_id

    @property
    def requested_by(self) -> str:
        return self.user_id

    def __repr__(self):
        return f'<ApiRequestTrigger (id={self.id}, project_id={self.project_id})>'
