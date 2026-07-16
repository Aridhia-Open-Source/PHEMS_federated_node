"""Replace is_processed boolean with status enum

Migrates pull_requests table from is_processed boolean to status enum with values:
unprocessed, in_progress, success, failed

Revision ID: h5c0d4f3g6b2
Revises: g4b9c3e2f5a1
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h5c0d4f3g6b2'
down_revision: Union[str, None] = 'g4b9c3e2f5a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new status column with default 'unprocessed'
    op.add_column(
        'pull_requests',
        sa.Column('status', sa.String(32), nullable=False, server_default='unprocessed')
    )
    # Drop the old index on is_processed
    op.drop_index('ix_pull_requests_unprocessed', table_name='pull_requests')
    # Drop the old boolean column
    op.drop_column('pull_requests', 'is_processed')
    # Create new index on status
    op.create_index('ix_pull_requests_status', 'pull_requests', ['repository_id', 'is_valid', 'status'])


def downgrade() -> None:
    # Drop the new index
    op.drop_index('ix_pull_requests_status', table_name='pull_requests')
    # Add back the old boolean column
    op.add_column(
        'pull_requests',
        sa.Column('is_processed', sa.Boolean(), nullable=False, server_default='false')
    )
    # Drop the status column
    op.drop_column('pull_requests', 'status')
    # Recreate the old index
    op.create_index('ix_pull_requests_unprocessed', 'pull_requests', ['repository_id', 'is_valid', 'is_processed'])
