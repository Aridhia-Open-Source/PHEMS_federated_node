"""remove ml and dashboard from containers

Revision ID: a18ca22994f6
Revises: 989f740f31f8
Create Date: 2026-04-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a18ca22994f6'
down_revision = '8faa556d4f76'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('containers', 'ml')
    op.drop_column('containers', 'dashboard')


def downgrade() -> None:
    op.add_column('containers', sa.Column('ml', sa.BOOLEAN(), autoincrement=False, nullable=True))
    op.add_column('containers', sa.Column('dashboard', sa.BOOLEAN(), autoincrement=False, nullable=True))
    op.execute("UPDATE containers SET ml = false, dashboard = false")
