"""Split the result's state into step and state, and add the project lock.

Revision ID: 002_result_step_state_project_lock
Revises: 001_baseline
Create Date: 2026-10-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_result_step_state_project_lock'
down_revision = '001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('pull_request_results', 'state', new_column_name='step')
    op.add_column(
        'pull_request_results',
        sa.Column('state', sa.String(length=32), nullable=False, server_default='IN_PROGRESS'),
    )
    # A delivery that got as far as the pull request is delivered; the rest are not yet.
    # The failed ones were not recorded as such, so they resume as IN_PROGRESS.
    op.execute(
        "UPDATE pull_request_results SET state = 'DELIVERED' WHERE step IN ('OPENED', 'MERGED', 'CLOSED')"
    )
    op.add_column(
        'projects',
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('projects', 'locked')
    op.drop_column('pull_request_results', 'state')
    op.alter_column('pull_request_results', 'step', new_column_name='state')
