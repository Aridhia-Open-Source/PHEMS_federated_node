"""
Delivery targets.

`type` is the transport; auth lives in the config. The task-controller's auth_type enum
(Bearer, Basic, AzCopy) conflates the two - Bearer and Basic are schemes over one
transport, AzCopy is a different transport. So other+Bearer|Basic maps to http and
other+AzCopy to azcopy.

A target belongs to a project, not to a trigger repository. A task submitted through the
API has no repository, so a repository-owned target could never route it.

No credential or pointer to one is stored: the secret is derived from the target, the way
Dataset.get_creds_secret_name() derives a dataset's.

`config` is a JSON blob whose shape depends on `type`. Nothing validates it yet:
    github  repository ("owner/name", required), base_branch ("main"), results_dir ("")
    http    url (required), auth_scheme ("Bearer" or "Basic", default "Bearer")
    azcopy  url (container or blob URI, no SAS token, required), prefix ("")
"""
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db


class DeliveryTargetType(str, Enum):
    GITHUB = "github"
    HTTP = "http"
    AZCOPY = "azcopy"

    def __str__(self):
        return self.value


class HttpAuthScheme(str, Enum):
    """Spelled as the task-controller spells them, minus AzCopy."""

    BEARER = "Bearer"
    BASIC = "Basic"

    def __str__(self):
        return self.value


class DeliveryTarget(db.Model, BaseModel):
    """
    Where a repository's results go.

    Reconfiguring inserts a new row and disables the old one rather than mutating, so
    historical task_deliveries still resolve to the target that received them.
    """

    __tablename__ = 'delivery_targets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    type = Column(String(32), nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    project_id = Column(
        Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )
    enabled = Column(Boolean, nullable=False, server_default='true')
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())

    project = relationship("Project", back_populates="delivery_targets")
    deliveries = relationship("TaskDelivery", back_populates="target")

    # Partial, so a disabled row can stay behind when a project's target is replaced and
    # historical deliveries still resolve to the one that handled them.
    __table_args__ = (
        Index(
            'uq_delivery_targets_enabled_project',
            'project_id',
            unique=True,
            postgresql_where=text('enabled'),
        ),
        Index('ix_delivery_targets_project_enabled', 'project_id', 'enabled'),
    )

    @classmethod
    def for_project(cls, project_id: int):
        """The enabled target for a project, or None. Matches the partial unique index."""
        return cls.query.filter(
            cls.project_id == project_id, cls.enabled.is_(True)
        ).one_or_none()

    def __init__(self, name: str, target_type: str, config: dict, project_id: int):
        self.name = name
        self.type = DeliveryTargetType(target_type).value
        self.config = config
        self.project_id = project_id

    def __repr__(self):
        return f'<DeliveryTarget ({self.name}, {self.type})>'
