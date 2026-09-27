"""Task delivery attempt model, and the states an attempt can be in."""
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db


class DeliveryStatus(str, Enum):
    """
    What a delivery attempt is doing. Deliberately not TaskStatus: sending results
    somewhere cannot be queued or cancelled the way a run can, so borrowing that enum
    would permit states the column never holds.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"

    def __str__(self):
        return self.value


class TaskDelivery(db.Model, BaseModel):
    """One attempt at delivering a task's results."""

    __tablename__ = 'task_deliveries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False)
    target_id = Column(Integer, ForeignKey('delivery_targets.id', ondelete='RESTRICT'), nullable=False)
    dagster_run_id = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, server_default=DeliveryStatus.PENDING.value)
    attempt = Column(Integer, nullable=False, server_default='1')
    location = Column(String(2048), nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=False), nullable=True)
    completed_at = Column(DateTime(timezone=False), nullable=True)

    task = relationship("Task")
    target = relationship("DeliveryTarget", back_populates="deliveries")

    __table_args__ = (
        UniqueConstraint('task_id', 'target_id', 'attempt', name='uq_task_deliveries_attempt'),
        Index('ix_task_deliveries_task_id', 'task_id'),
    )

    def __init__(self, task_id: int, target_id: int, attempt: int = 1):
        self.task_id = task_id
        self.target_id = target_id
        self.attempt = attempt
        self.status = DeliveryStatus.PENDING.value

    def __repr__(self):
        return f'<TaskDelivery (task={self.task_id}, target={self.target_id}, attempt={self.attempt})>'
