"""Store a task spec's tags, config and metadata, drop its resources.

The tags are copied onto the task's run, the config is the JSON file the task reads and the
metadata is the client's own, from the spec file. The resources were never set by a pull
request task, so they go.

Revision ID: 003_task_spec_tags_config
Revises: 002_task_spec_resources
Create Date: 2026-10-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_task_spec_tags_config'
down_revision = '002_task_spec_resources'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('task_specs', sa.Column('tags', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('task_specs', sa.Column('config', sa.JSON(), nullable=True))
    op.add_column('task_specs', sa.Column('metadata', sa.JSON(), nullable=True))
    op.drop_column('task_specs', 'resources')


def downgrade() -> None:
    op.add_column('task_specs', sa.Column('resources', sa.JSON(), nullable=False, server_default='{}'))
    op.drop_column('task_specs', 'metadata')
    op.drop_column('task_specs', 'config')
    op.drop_column('task_specs', 'tags')
