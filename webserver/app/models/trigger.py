import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import sqla_column
from app.models.trigger_state import TriggerState


class Trigger(db.Model, BaseModel):
    """
    Why a task ran: the record of a request to run one, and the outcome of validating it.
    Never changed by the runs it leads to. Each kind of trigger is a child table sharing
    this id, picked by `type`.

    A Task is created only when the trigger is valid, and then `state` is YIELDED.
    """
    __tablename__ = 'triggers'
    __mapper_args__ = {'polymorphic_on': 'type'}

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    type = sa.Column(sa.String(16), nullable=False)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )
    state = sa.Column(
        sa.String(32),
        nullable=False,
        default=TriggerState.UNKNOWN.value,
        server_default=TriggerState.UNKNOWN.value,
    )
    # Why the trigger is IGNORED or REJECTED. Set for those two states only.
    reason = sa.Column(sa.String(1024), nullable=True)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    project = relationship('Project', back_populates='triggers')
    task = relationship('Task', back_populates='trigger', uselist=False)

    __table_args__ = (
        sa.CheckConstraint(
            "(state IN ('IGNORED', 'REJECTED')) = (reason IS NOT NULL)",
            name='ck_triggers_reason_for_ignored_rejected',
        ),
        sa.Index('ix_triggers_state', 'state'),
    )

    def __init__(self, project_id: int):
        self.project_id = project_id
        self.state = TriggerState.UNKNOWN.value

    @property
    def requested_by(self) -> str:
        raise NotImplementedError

    @property
    def task_id(self) -> int | None:
        return self.task.id if self.task else None

    def set_state(self, state: str, reason: str | None):
        """
        Set the state with its reason, which is required for IGNORED and REJECTED and
        not allowed otherwise.
        """
        if state not in [s.value for s in TriggerState]:
            valid = ', '.join([s.value for s in TriggerState])
            raise InvalidRequest(f"Invalid state: {state}. Must be one of: {valid}")
        needs_reason = state in (TriggerState.IGNORED.value, TriggerState.REJECTED.value)
        if needs_reason and not reason:
            raise InvalidRequest(f"reason is required when state is {state}")
        if not needs_reason and reason is not None:
            raise InvalidRequest(f"reason is not allowed when state is {state}")
        self.state = state
        self.reason = reason
