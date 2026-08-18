"""Point DARs at projects

requests.project_name stays for now so nothing at the wire moves, but the project a DAR
belongs to is derived from its dataset rather than taken from the submitted string.

Revision ID: f3a6e91b04c7
Revises: b8d1c50f7a92
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a6e91b04c7'
down_revision: Union[str, None] = 'b8d1c50f7a92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requests', sa.Column('project_id', sa.Integer(), nullable=True))

    # From the dataset, not from project_name, so a DAR cannot end up naming a project
    # that does not own the dataset it grants access to.
    op.execute(
        """
        UPDATE requests r
        SET project_id = d.project_id
        FROM datasets d
        WHERE d.id = r.dataset_id
        """
    )

    op.create_foreign_key(
        'fk_requests_project', 'requests', 'projects', ['project_id'], ['id'],
        ondelete='RESTRICT'
    )
    op.create_index('ix_requests_project_id', 'requests', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_requests_project_id', table_name='requests')
    op.drop_constraint('fk_requests_project', 'requests', type_='foreignkey')
    op.drop_column('requests', 'project_id')
