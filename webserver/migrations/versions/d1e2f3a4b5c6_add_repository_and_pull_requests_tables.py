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
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('uri', sa.String(length=4096), nullable=False, unique=True),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False, server_default='main'),
        sa.Column('default_dataset_name', sa.String(length=256), nullable=True),
        sa.Column('initial_cursor', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uri', name='uq_repositories_uri'),
    )

    # Create pull_requests table
    op.create_table(
        'pull_requests',
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('raised_by', sa.String(length=256), nullable=False),
        sa.Column('merged_at', sa.DateTime(timezone=False), nullable=False),
        sa.Column('saved_at', sa.DateTime(timezone=False), server_default=sa.func.now()),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='UNKNOWN'),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('repository_id', 'number', 'dataset_id'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_pull_requests_status', 'pull_requests', ['repository_id', 'dataset_id', 'status'])

    # Add repository_id column to datasets table
    op.add_column('datasets', sa.Column('repository_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_datasets_repository_id', 'datasets', 'repositories', ['repository_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_datasets_repository_id', 'datasets', type_='foreignkey')
    op.drop_column('datasets', 'repository_id')
    op.drop_table('pull_requests')
    op.drop_table('repositories')
