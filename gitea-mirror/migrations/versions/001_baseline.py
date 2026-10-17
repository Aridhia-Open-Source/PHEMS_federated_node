"""Baseline schema with gitea mirror tables.

Revision ID: 001_baseline
Revises:
Create Date: 2026-10-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create mirrors table (no dependencies)
    op.create_table(
        'mirrors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('upstream_uri', sa.String(length=256), nullable=False, unique=True),
        sa.Column('secret_namespace', sa.String(length=256), nullable=False),
        sa.Column('secret_key', sa.String(length=256), nullable=False),
        sa.Column('gitea_owner', sa.String(length=256), nullable=False),
        sa.Column('gitea_repo', sa.String(length=256), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('gitea_owner', 'gitea_repo'),
    )

    # Create mirror_state table
    op.create_table(
        'mirror_state',
        sa.Column('mirror_id', sa.Integer(), nullable=False),
        sa.Column('cursor', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(length=4096), nullable=True),
        sa.ForeignKeyConstraint(['mirror_id'], ['mirrors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('mirror_id'),
    )

    # Create mirrored_pull_requests table
    op.create_table(
        'mirrored_pull_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mirror_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('merge_commit_sha', sa.String(length=256), nullable=False),
        sa.Column('merged_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('author', sa.String(length=256), nullable=False),
        sa.Column('gitea_pr_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('mirrored_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['mirror_id'], ['mirrors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mirror_id', 'number'),
    )

    # Create webhooks table
    op.create_table(
        'webhooks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('secret_namespace', sa.String(length=256), nullable=False),
        sa.Column('secret_key', sa.String(length=256), nullable=False),
        sa.Column('mirror_id', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['mirror_id'], ['mirrors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create webhook_deliveries table
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('delivery_uuid', sa.String(length=36), nullable=False),
        sa.Column('webhook_id', sa.Integer(), nullable=False),
        sa.Column('mirrored_pull_request_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(length=4096), nullable=True),
        sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mirrored_pull_request_id'], ['mirrored_pull_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('delivery_uuid'),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name='ck_webhook_deliveries_status'),
    )
    op.create_index('ix_webhook_deliveries_status_next_attempt_at', 'webhook_deliveries', ['status', 'next_attempt_at'])
    op.create_index('ix_webhook_deliveries_webhook_id', 'webhook_deliveries', ['webhook_id'])
    op.create_index('ix_webhook_deliveries_mirrored_pull_request_id', 'webhook_deliveries', ['mirrored_pull_request_id'])


def downgrade() -> None:
    op.drop_index('ix_webhook_deliveries_mirrored_pull_request_id', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_webhook_id', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_status_next_attempt_at', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
    op.drop_table('webhooks')
    op.drop_table('mirrored_pull_requests')
    op.drop_table('mirror_state')
    op.drop_table('mirrors')
