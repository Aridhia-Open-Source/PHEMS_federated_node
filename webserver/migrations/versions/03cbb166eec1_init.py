"""init

Revision ID: 03cbb166eec1
Revises:
Create Date: 2024-01-23 13:30:31.456451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '03cbb166eec1'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('audit',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ip_address', sa.String(length=15), nullable=False),
    sa.Column('http_method', sa.String(length=10), nullable=False),
    sa.Column('endpoint', sa.String(length=50), nullable=False),
    sa.Column('requested_by', sa.String(length=50), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('api_function', sa.String(length=50), nullable=True),
    sa.Column('details', sa.String(length=256), nullable=True),
    sa.Column('event_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('datasets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('host', sa.String(length=120), nullable=False),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('catalogues',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('version', sa.String(length=10), nullable=True),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('description', sa.String(length=2048), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('title', 'dataset_id')
    )
    op.create_table('dictionaries',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('table_name', sa.String(length=50), nullable=False),
    sa.Column('field_name', sa.String(length=50), nullable=True),
    sa.Column('label', sa.String(length=64), nullable=True),
    sa.Column('description', sa.String(length=2048), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('table_name', 'dataset_id', 'field_name')
    )
    op.create_table('requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('description', sa.String(length=2048), nullable=True),
    sa.Column('requested_by', sa.String(length=64), nullable=False),
    sa.Column('project_name', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('proj_start', sa.DateTime(), nullable=False),
    sa.Column('proj_end', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tasks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('docker_image', sa.String(length=256), nullable=False),
    sa.Column('description', sa.String(length=2048), nullable=True),
    sa.Column('status', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('requested_by', sa.String(length=64), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('tasks')
    op.drop_table('requests')
    op.drop_table('dictionaries')
    op.drop_table('catalogues')
    op.drop_table('datasets')
    op.drop_table('audit')
    # ### end Alembic commands ###
