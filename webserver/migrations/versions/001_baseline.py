"""Baseline schema with results delivery models.

Revision ID: 001_baseline
Revises:
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create results_repositories table first (no dependencies)
    op.create_table(
        'results_repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('owned_by_federated_node', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uri'),
    )

    # Create projects table
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('default_dataset_id', sa.Integer(), nullable=True),
        sa.Column('results_repository_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['results_repository_id'], ['results_repositories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_projects_id', 'projects', ['id'])

    # Create datasets table
    op.create_table(
        'datasets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('host', sa.String(length=256), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default=sa.literal_column('5432')),
        sa.Column('schema', sa.String(length=256), nullable=True),
        sa.Column('schema_write', sa.String(length=256), nullable=True),
        sa.Column('type', sa.String(length=256), nullable=False, server_default='postgres'),
        sa.Column('extra_connection_args', sa.String(length=4096), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # Create trigger_repositories table
    op.create_table(
        'trigger_repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False, server_default='main'),
        sa.Column('initial_cursor', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uri'),
    )

    # Create pull_request_status enum table (if needed)
    op.create_table(
        'pull_request_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create pull_requests table
    op.create_table(
        'pull_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trigger_repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('author', sa.String(length=256), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(256), nullable=False, server_default='UNKNOWN'),
        sa.Column('merged_at', sa.DateTime(), nullable=True),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=True),
        sa.Column('raised_by', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['trigger_repository_id'], ['trigger_repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trigger_repository_id', 'number'),
    )

    # Create task_status enum table (if needed)
    op.create_table(
        'task_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create requests table (Data Access Requests - separate from api_requests)
    op.create_table(
        'requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create api_requests table (NEW - API trigger requests)
    op.create_table(
        'api_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=256), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='UNKNOWN'),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create results_backends table (NEW)
    op.create_table(
        'results_backends',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False, server_default='git'),
        sa.Column('config', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id'),
    )

    # Create task_requests table (NEW - unified trigger entity)
    op.create_table(
        'task_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pull_request_id', sa.Integer(), nullable=True),
        sa.Column('api_request_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='UNKNOWN'),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['api_request_id'], ['api_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create tasks table
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('pr_repository_id', sa.Integer(), nullable=True),
        sa.Column('pr_number', sa.Integer(), nullable=True),
        sa.Column('api_request_id', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('docker_image', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('status', sa.String(length=256), nullable=False, server_default='scheduled'),
        sa.Column('requested_by', sa.String(length=256), nullable=False),
        sa.Column('review_status', sa.Boolean(), nullable=True),
        sa.Column('trigger_source', sa.String(length=16), nullable=False, server_default='API'),
        sa.Column('dagster_run_id', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(length=256), nullable=True),
        sa.Column('artifact_key', sa.String(length=512), nullable=True),
        sa.Column('params', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('reviewed_by', sa.String(length=256), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('git_commit_sha', sa.String(length=40), nullable=True),
        sa.Column('results_path', sa.String(length=512), nullable=True),
        sa.Column('trigger_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['api_request_id'], ['api_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['request_id'], ['requests.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dagster_run_id'),
    )
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])

    # Create whitelisted_images table
    op.create_table(
        'whitelisted_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('image', sa.String(length=512), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'image'),
    )

    # Create catalogues table
    op.create_table(
        'catalogues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id', 'field_name'),
    )

    # Create dictionaries table
    op.create_table(
        'dictionaries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(length=256), nullable=False),
        sa.Column('definition', sa.String(length=4096), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id', 'field_name'),
    )

    # Create registries table
    op.create_table(
        'registries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Add deferred FK for default_dataset_id (circular dependency)
    op.create_foreign_key('fk_projects_default_dataset_id', 'projects', 'datasets',
                         ['default_dataset_id'], ['id'], ondelete='RESTRICT', deferrable=True, initially='DEFERRED')


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('registries')
    op.drop_table('dictionaries')
    op.drop_table('catalogues')
    op.drop_table('whitelisted_images')
    op.drop_table('task_requests')
    op.drop_index('ix_tasks_project_id', 'tasks')
    op.drop_table('tasks')
    op.drop_table('results_backends')
    op.drop_table('api_requests')
    op.drop_table('requests')
    op.drop_table('task_statuses')
    op.drop_table('pull_requests')
    op.drop_table('pull_request_statuses')
    op.drop_table('trigger_repositories')
    op.drop_table('datasets')
    op.drop_index('ix_projects_id', 'projects')
    op.drop_table('projects')
    op.drop_table('results_repositories')
