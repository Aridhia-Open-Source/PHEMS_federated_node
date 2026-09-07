"""Projects, and dataset ownership by project

Creates the projects table and gives every dataset an owning project. Also drops
datasets.repository, which has never been written: Dataset.__init__ accepted the keyword
and discarded it, so the column is NULL on every row that exists.

Revision ID: b8d1c50f7a92
Revises: e7a4c9b21d38
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d1c50f7a92'
down_revision: Union[str, None] = 'e7a4c9b21d38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors DEFAULT_PROJECT_NAME in app/models/project.py. Datasets with no DAR to derive a
# project from land here.
DEFAULT_PROJECT_NAME = 'default'


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='projects_pkey'),
        sa.UniqueConstraint('name', name='uq_projects_name'),
    )

    op.add_column('datasets', sa.Column('project_id', sa.Integer(), nullable=True))

    # One project per distinct project name already in use.
    op.execute(
        """
        INSERT INTO projects (name)
        SELECT DISTINCT project_name FROM requests WHERE project_name IS NOT NULL
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        f"INSERT INTO projects (name) VALUES ('{DEFAULT_PROJECT_NAME}') "
        "ON CONFLICT (name) DO NOTHING"
    )

    # Each dataset takes the project named by its most recent DAR. A dataset can be
    # referenced by DARs naming different projects; the newest wins rather than failing.
    op.execute(
        """
        UPDATE datasets d
        SET project_id = p.id
        FROM (
            SELECT DISTINCT ON (r.dataset_id) r.dataset_id, r.project_name
            FROM requests r
            WHERE r.dataset_id IS NOT NULL AND r.project_name IS NOT NULL
            ORDER BY r.dataset_id, r.created_at DESC, r.id DESC
        ) latest
        JOIN projects p ON p.name = latest.project_name
        WHERE d.id = latest.dataset_id
        """
    )
    op.execute(
        f"""
        UPDATE datasets
        SET project_id = (SELECT id FROM projects WHERE name = '{DEFAULT_PROJECT_NAME}')
        WHERE project_id IS NULL
        """
    )

    op.alter_column('datasets', 'project_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        'fk_datasets_project', 'datasets', 'projects', ['project_id'], ['id'],
        ondelete='RESTRICT'
    )
    op.create_index('ix_datasets_project_id', 'datasets', ['project_id'])

    op.drop_column('datasets', 'repository')


def downgrade() -> None:
    op.add_column('datasets', sa.Column('repository', sa.String(length=4096), nullable=True))
    op.drop_index('ix_datasets_project_id', table_name='datasets')
    op.drop_constraint('fk_datasets_project', 'datasets', type_='foreignkey')
    op.drop_column('datasets', 'project_id')
    op.drop_table('projects')
