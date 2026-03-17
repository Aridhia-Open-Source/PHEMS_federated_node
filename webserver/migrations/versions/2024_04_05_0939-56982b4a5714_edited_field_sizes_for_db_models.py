"""Edited field sizes for DB models

Revision ID: 56982b4a5714
Revises: 03cbb166eec1
Create Date: 2024-04-05 09:39:31.087602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '56982b4a5714'
down_revision: Union[str, None] = '03cbb166eec1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('catalogues', 'version',
               existing_type=sa.VARCHAR(length=10),
               type_=sa.String(length=256),
               existing_nullable=True)
    op.alter_column('catalogues', 'description',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.String(length=4096),
               existing_nullable=False)
    op.alter_column('datasets', 'name',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('datasets', 'host',
               existing_type=sa.VARCHAR(length=120),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('dictionaries', 'table_name',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('dictionaries', 'field_name',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=256),
               existing_nullable=True)
    op.alter_column('dictionaries', 'label',
               existing_type=sa.VARCHAR(length=64),
               type_=sa.String(length=256),
               existing_nullable=True)
    op.alter_column('dictionaries', 'description',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.String(length=4096),
               existing_nullable=False)
    op.alter_column('requests', 'description',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.String(length=4096),
               existing_nullable=True)
    op.alter_column('requests', 'requested_by',
               existing_type=sa.VARCHAR(length=64),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('requests', 'project_name',
               existing_type=sa.VARCHAR(length=64),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('requests', 'status',
               existing_type=sa.VARCHAR(length=32),
               type_=sa.String(length=256),
               existing_nullable=True)
    op.alter_column('tasks', 'description',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.String(length=4096),
               existing_nullable=True)
    op.alter_column('tasks', 'status',
               existing_type=sa.VARCHAR(length=64),
               type_=sa.String(length=256),
               existing_nullable=True)
    op.alter_column('tasks', 'requested_by',
               existing_type=sa.VARCHAR(length=64),
               type_=sa.String(length=256),
               existing_nullable=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.alter_column('tasks', 'requested_by',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=64),
               existing_nullable=False)
    op.alter_column('tasks', 'status',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=64),
               existing_nullable=True)
    op.alter_column('tasks', 'description',
               existing_type=sa.String(length=4096),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=True)
    op.alter_column('requests', 'status',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=32),
               existing_nullable=True)
    op.alter_column('requests', 'project_name',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=64),
               existing_nullable=False)
    op.alter_column('requests', 'requested_by',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=64),
               existing_nullable=False)
    op.alter_column('requests', 'description',
               existing_type=sa.String(length=4096),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=True)
    op.alter_column('dictionaries', 'description',
               existing_type=sa.String(length=4096),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=False)
    op.alter_column('dictionaries', 'label',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=64),
               existing_nullable=True)
    op.alter_column('dictionaries', 'field_name',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
    op.alter_column('dictionaries', 'table_name',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    op.alter_column('datasets', 'host',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=120),
               existing_nullable=False)
    op.alter_column('datasets', 'name',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    op.alter_column('catalogues', 'description',
               existing_type=sa.String(length=4096),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=False)
    op.alter_column('catalogues', 'version',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=10),
               existing_nullable=True)
    # ### end Alembic commands ###
