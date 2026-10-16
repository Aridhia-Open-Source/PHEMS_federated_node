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


class MirrorState(Base):
    __tablename__ = 'mirror_state'

    mirror_id = Column(Integer, ForeignKey('mirrors.id', ondelete='CASCADE'), primary_key=True)
    cursor = Column(DateTime(timezone=True), nullable=True)
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
    webhook_id = Column(Integer, ForeignKey('webhooks.id', ondelete='CASCADE'), nullable=False)
    mirrored_pull_request_id = Column(Integer, ForeignKey('mirrored_pull_requests.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(64), nullable=False, server_default='pending')
    attempts = Column(Integer, nullable=False, server_default='0')
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(4096), nullable=True)
