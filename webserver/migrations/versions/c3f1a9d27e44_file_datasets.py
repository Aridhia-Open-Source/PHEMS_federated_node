"""File based datasets (duckdb, sqlite)

Revision ID: c3f1a9d27e44
Revises: a18ca22994f6
Create Date: 2026-09-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f1a9d27e44'
down_revision: Union[str, None] = 'a18ca22994f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('datasets', 'host', existing_type=sa.String(length=256), nullable=True)
    op.add_column('datasets', sa.Column('volume_claim', sa.String(length=256), nullable=True))
    op.add_column('datasets', sa.Column('path', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column('datasets', 'path')
    op.drop_column('datasets', 'volume_claim')
    op.alter_column('datasets', 'host', existing_type=sa.String(length=256), nullable=False)
