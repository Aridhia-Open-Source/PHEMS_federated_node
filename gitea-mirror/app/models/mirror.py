import uuid

import sqlalchemy as sa
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from app.helpers.base_model import Base


class Mirror(Base):
    __tablename__ = 'mirrors'

    id = Column(Integer, primary_key=True)
    upstream_uri = Column(String(256), nullable=False, unique=True)
    secret_namespace = Column(String(256), nullable=False)
    secret_key = Column(String(256), nullable=False)
    gitea_owner = Column(String(256), nullable=False)
    gitea_repo = Column(String(256), nullable=False)
    base_branch = Column(String(256), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default='false')

    __table_args__ = (
        sa.UniqueConstraint('gitea_owner', 'gitea_repo'),
    )


class MirrorState(Base):
    __tablename__ = 'mirror_state'

    mirror_id = Column(Integer, ForeignKey('mirrors.id', ondelete='CASCADE'), primary_key=True)
    cursor = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(4096), nullable=True)


class MirroredPullRequest(Base):
    __tablename__ = 'mirrored_pull_requests'

    id = Column(Integer, primary_key=True)
    mirror_id = Column(Integer, ForeignKey('mirrors.id', ondelete='CASCADE'), nullable=False)
    number = Column(Integer, nullable=False)
    merge_commit_sha = Column(String(256), nullable=False)
    merged_at = Column(DateTime(timezone=True), nullable=False)
    author = Column(String(256), nullable=False)
    gitea_pr_number = Column(Integer, nullable=False)
    title = Column(String(512), nullable=False)
    mirrored_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        sa.UniqueConstraint('mirror_id', 'number'),
    )


class Webhook(Base):
    __tablename__ = 'webhooks'

    id = Column(Integer, primary_key=True)
    url = Column(String(512), nullable=False)
    secret_namespace = Column(String(256), nullable=False)
    secret_key = Column(String(256), nullable=False)
    mirror_id = Column(Integer, ForeignKey('mirrors.id', ondelete='CASCADE'), nullable=True)
    enabled = Column(Boolean, nullable=False, server_default='true')


class WebhookDelivery(Base):
    __tablename__ = 'webhook_deliveries'

    id = Column(Integer, primary_key=True)
    # Stable unique id sent to receivers (the integer id repeats after a database reset).
    delivery_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    webhook_id = Column(Integer, ForeignKey('webhooks.id', ondelete='CASCADE'), nullable=False)
    mirrored_pull_request_id = Column(Integer, ForeignKey('mirrored_pull_requests.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(64), nullable=False, server_default='pending')
    attempts = Column(Integer, nullable=False, server_default='0')
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(4096), nullable=True)

    __table_args__ = (
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name='ck_webhook_deliveries_status'),
        sa.Index('ix_webhook_deliveries_status_next_attempt_at', 'status', 'next_attempt_at'),
        sa.Index('ix_webhook_deliveries_webhook_id', 'webhook_id'),
        sa.Index('ix_webhook_deliveries_mirrored_pull_request_id', 'mirrored_pull_request_id'),
    )
