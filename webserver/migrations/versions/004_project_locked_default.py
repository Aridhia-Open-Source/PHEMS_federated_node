"""New projects start locked, so their links can be set up before anything runs.

Revision ID: 004_project_locked_default
Revises: 003_pr_merge_sha_unique
Create Date: 2026-10-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_project_locked_default'
down_revision = '003_pr_merge_sha_unique'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('projects', 'locked', server_default=sa.true())


def downgrade() -> None:
    op.alter_column('projects', 'locked', server_default=sa.false())
