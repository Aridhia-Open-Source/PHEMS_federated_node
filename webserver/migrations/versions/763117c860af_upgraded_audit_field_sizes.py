"""Upgraded audit field sizes

Revision ID: 763117c860af
Revises: 56982b4a5714
Create Date: 2024-05-29 09:00:39.835886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '763117c860af'
down_revision: Union[str, None] = '56982b4a5714'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('audit', 'ip_address',
               existing_type=sa.VARCHAR(length=15),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('audit', 'http_method',
               existing_type=sa.VARCHAR(length=10),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('audit', 'endpoint',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('audit', 'requested_by',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=256),
               existing_nullable=False)
    op.alter_column('audit', 'api_function',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=256),
               existing_nullable=True)
    op.alter_column('audit', 'details',
               existing_type=sa.VARCHAR(length=256),
               type_=sa.String(length=4096),
               existing_nullable=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('audit', 'details',
               existing_type=sa.String(length=4096),
               type_=sa.VARCHAR(length=256),
               existing_nullable=True)
    op.alter_column('audit', 'api_function',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
    op.alter_column('audit', 'requested_by',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    op.alter_column('audit', 'endpoint',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    op.alter_column('audit', 'http_method',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=10),
               existing_nullable=False)
    op.alter_column('audit', 'ip_address',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=15),
               existing_nullable=False)
    # ### end Alembic commands ###