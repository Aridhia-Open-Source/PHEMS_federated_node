"""Add pull_requests table

Stores GitHub PRs merged to watched repositories for async processing
by Dagster ingest/trigger sensors.

Revision ID: g4b9c3e2f5a1
Revises: f3a8b9c2d1e4
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g4b9c3e2f5a1'
down_revision: Union[str, None] = 'f3a8b9c2d1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pull_requests',
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('raised_by', sa.String(length=256), nullable=False),
        sa.Column('merged_at', sa.DateTime(), nullable=False),
        sa.Column('saved_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('repository_id', 'number'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_pull_requests_unprocessed', 'pull_requests', ['repository_id', 'is_valid', 'is_processed'])


def downgrade() -> None:
    op.drop_table('pull_requests')
