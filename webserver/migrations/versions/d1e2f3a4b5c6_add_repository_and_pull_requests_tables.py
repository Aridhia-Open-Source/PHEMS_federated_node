"""Add repository and pull_requests tables

Creates tables for storing GitHub repository metadata and merged pull requests
for async processing by Dagster ingest/trigger sensors.

Revision ID: d1e2f3a4b5c6
Revises: a18ca22994f6
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'a18ca22994f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create repositories table
    op.create_table(
        'repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('github_repo_id', sa.Integer(), nullable=False),
        sa.Column('owner', sa.String(length=256), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('saved_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('github_repo_id', name='uq_repositories_github_repo_id'),
    )
    op.create_index('ix_repositories_owner_name', 'repositories', ['owner', 'name'])

    # Create pull_requests table
    op.create_table(
        'pull_requests',
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('raised_by', sa.String(length=256), nullable=False),
        sa.Column('merged_at', sa.DateTime(), nullable=False),
        sa.Column('saved_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='unprocessed'),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('repository_id', 'number', 'dataset_id'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_pull_requests_status', 'pull_requests', ['repository_id', 'dataset_id', 'is_valid', 'status'])


def downgrade() -> None:
    op.drop_table('pull_requests')
    op.drop_table('repositories')
