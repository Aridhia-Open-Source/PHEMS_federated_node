"""Project-scoped resources

Gives a project a default dataset, makes every task state its project, scopes the image
allow list to a project, and creates the delivery tables owned by a project.

A task submitted through the API has no trigger repository, so a delivery target hung off
one could never route it. A project is the owner every task can reach.

Revision ID: d4b7e2196f05
Revises: f3a6e91b04c7
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4b7e2196f05'
down_revision: Union[str, None] = 'f3a6e91b04c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The project b8d1c50f7a92 creates for anything it could not attribute. Rows that predate
# project ownership land here.
FALLBACK_PROJECT_NAME = 'default'


def upgrade() -> None:
    # projects.default_dataset_id. The FK is added separately because datasets.project_id
    # already points the other way, and a circular reference cannot be declared inline.
    op.add_column('projects', sa.Column('default_dataset_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_projects_default_dataset', 'projects', 'datasets',
        ['default_dataset_id'], ['id'], ondelete='SET NULL',
    )
    # Lowest id wins. Arbitrary but deterministic, and an admin can change it.
    op.execute(
        """
        UPDATE projects p
        SET default_dataset_id = (
            SELECT MIN(d.id) FROM datasets d WHERE d.project_id = p.id
        )
        """
    )

    # tasks.project_id
    op.add_column('tasks', sa.Column('project_id', sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE tasks t
        SET project_id = d.project_id
        FROM datasets d
        WHERE d.id = t.dataset_id
        """
    )
    op.execute(
        f"""
        UPDATE tasks
        SET project_id = (SELECT id FROM projects WHERE name = '{FALLBACK_PROJECT_NAME}')
        WHERE project_id IS NULL
        """
    )
    op.alter_column('tasks', 'project_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        'fk_tasks_project', 'tasks', 'projects', ['project_id'], ['id'], ondelete='RESTRICT',
    )
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])

    # whitelisted_images.project_id. Existing entries were node-wide, so they all land in
    # the fallback project rather than being duplicated per project.
    op.add_column('whitelisted_images', sa.Column('project_id', sa.Integer(), nullable=True))
    op.execute(
        f"""
        UPDATE whitelisted_images
        SET project_id = (SELECT id FROM projects WHERE name = '{FALLBACK_PROJECT_NAME}')
        WHERE project_id IS NULL
        """
    )
    op.alter_column(
        'whitelisted_images', 'project_id', existing_type=sa.Integer(), nullable=False,
    )
    op.create_foreign_key(
        'fk_whitelisted_images_project', 'whitelisted_images', 'projects',
        ['project_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index('ix_whitelisted_images_project_id', 'whitelisted_images', ['project_id'])

    # trigger_repositories.dataset_id -> project_id. The dataset it named is now the
    # project's default, so a repository binds to the project and a PR gets that default
    # until a spec is allowed to name a dataset of its own.
    op.add_column('trigger_repositories', sa.Column('project_id', sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE trigger_repositories r
        SET project_id = d.project_id
        FROM datasets d
        WHERE d.id = r.dataset_id
        """
    )
    op.alter_column(
        'trigger_repositories', 'project_id', existing_type=sa.Integer(), nullable=False,
    )
    op.create_foreign_key(
        'fk_trigger_repositories_project', 'trigger_repositories', 'projects',
        ['project_id'], ['id'], ondelete='RESTRICT',
    )
    op.create_index('ix_trigger_repositories_project_id', 'trigger_repositories', ['project_id'])
    op.drop_constraint(
        'trigger_repositories_dataset_id_fkey', 'trigger_repositories', type_='foreignkey'
    )
    op.drop_column('trigger_repositories', 'dataset_id')

    op.create_table(
        'delivery_targets',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=False), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_delivery_targets_name'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    )
    # Partial, so a replaced target can stay behind as a disabled row and old deliveries
    # still resolve to the configuration that handled them.
    op.create_index(
        'uq_delivery_targets_enabled_project', 'delivery_targets', ['project_id'],
        unique=True, postgresql_where=sa.text('enabled'),
    )
    op.create_index(
        'ix_delivery_targets_project_enabled', 'delivery_targets', ['project_id', 'enabled'],
    )

    op.create_table(
        'task_deliveries',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('dagster_run_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='PENDING'),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('location', sa.String(length=2048), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'target_id', 'attempt', name='uq_task_deliveries_attempt'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_id'], ['delivery_targets.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_task_deliveries_task_id', 'task_deliveries', ['task_id'])


def downgrade() -> None:
    op.drop_index('ix_task_deliveries_task_id', table_name='task_deliveries')
    op.drop_table('task_deliveries')

    op.drop_index('ix_delivery_targets_project_enabled', table_name='delivery_targets')
    op.drop_index('uq_delivery_targets_enabled_project', table_name='delivery_targets')
    op.drop_table('delivery_targets')

    op.drop_index('ix_whitelisted_images_project_id', table_name='whitelisted_images')
    op.drop_constraint('fk_whitelisted_images_project', 'whitelisted_images', type_='foreignkey')
    op.drop_column('whitelisted_images', 'project_id')

    op.drop_index('ix_tasks_project_id', table_name='tasks')
    op.drop_constraint('fk_tasks_project', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'project_id')

    op.add_column('trigger_repositories', sa.Column('dataset_id', sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE trigger_repositories r
        SET dataset_id = p.default_dataset_id
        FROM projects p
        WHERE p.id = r.project_id
        """
    )
    op.alter_column(
        'trigger_repositories', 'dataset_id', existing_type=sa.Integer(), nullable=False,
    )
    op.create_foreign_key(
        'trigger_repositories_dataset_id_fkey', 'trigger_repositories', 'datasets',
        ['dataset_id'], ['id'], ondelete='RESTRICT',
    )
    op.drop_index('ix_trigger_repositories_project_id', table_name='trigger_repositories')
    op.drop_constraint(
        'fk_trigger_repositories_project', 'trigger_repositories', type_='foreignkey'
    )
    op.drop_column('trigger_repositories', 'project_id')

    op.drop_constraint('fk_projects_default_dataset', 'projects', type_='foreignkey')
    op.drop_column('projects', 'default_dataset_id')
