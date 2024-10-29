"""field_name in Dictionaries non nullable

Revision ID: 3d3999b8de6a
Revises: 763117c860af
Create Date: 2024-10-28 15:39:48.295388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d3999b8de6a'
down_revision: Union[str, None] = '763117c860af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('dictionaries', 'field_name',
               existing_type=sa.VARCHAR(length=256),
               nullable=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('dictionaries', 'field_name',
               existing_type=sa.VARCHAR(length=256),
               nullable=True)
    # ### end Alembic commands ###
