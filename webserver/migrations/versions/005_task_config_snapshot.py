"""A task stores the configuration it was created under, and a hash of it.

Revision ID: 005_task_config_snapshot
Revises: 004_project_locked_default
Create Date: 2026-10-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_task_config_snapshot'
down_revision = '004_project_locked_default'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('config_snapshot', sa.JSON(), nullable=True))
    op.add_column('tasks', sa.Column('config_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'config_hash')
    op.drop_column('tasks', 'config_snapshot')
