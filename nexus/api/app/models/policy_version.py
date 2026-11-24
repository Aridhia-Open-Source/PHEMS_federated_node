"""
The Cedar policy files nexus-api started with (ADR 0037), one row per new hash, for audit. Written at startup
once the Cedar check lands.
"""
import sqlalchemy as sa

from app.database.base_model import BaseModel, db
from app.models import sqla_column


class PolicyVersion(db.Model, BaseModel):
    """One version of the policy files, by hash."""
    __tablename__ = 'policy_versions'
    __table_args__ = (sa.UniqueConstraint('hash', name='uq_policy_versions_hash'),)

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    # sha256 of the policy files, hex
    hash = sa.Column(sa.String(64), nullable=False)
    contents = sa.Column(sa.Text, nullable=False)
    created_at = sqla_column.created_at()
