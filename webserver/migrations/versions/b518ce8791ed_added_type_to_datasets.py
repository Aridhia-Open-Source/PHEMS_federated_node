"""Added type to datasets

Revision ID: b518ce8791ed
Revises: 763117c860af
Create Date: 2024-10-17 17:00:28.465625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b518ce8791ed'
down_revision: Union[str, None] = '763117c860af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('datasets', sa.Column('type', sa.String(length=256), server_default="postgres", nullable=False))
    op.add_column('datasets', sa.Column('extra_connection_args', sa.String(length=4096), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('datasets', 'type')
    op.drop_column('datasets', 'extra_connection_args')
    # ### end Alembic commands ###
