"""Store a task spec's resources.

The spec's CPU and memory requests and limits were validated and then dropped, so the task
pod never got them.

Revision ID: 002_task_spec_resources
Revises: 001_baseline
Create Date: 2026-10-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_task_spec_resources'
down_revision = '001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('task_specs', sa.Column('resources', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('task_specs', 'resources')
