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
    # Create audit table (no dependencies)
    op.create_table(
        'audit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ip_address', sa.String(length=256), nullable=False),
        sa.Column('http_method', sa.String(length=256), nullable=False),
        sa.Column('endpoint', sa.String(length=256), nullable=False),
        sa.Column('requested_by', sa.String(length=256), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('api_function', sa.String(length=256), nullable=True),
        sa.Column('details', sa.String(length=4096), nullable=True),
        sa.Column('event_time', sa.DateTime(timezone=False), nullable=True, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

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
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('default_dataset_id', sa.Integer(), nullable=True),
        sa.Column('results_repository_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['results_repository_id'], ['results_repositories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_projects_id', 'projects', ['id'])

    # Create k8s_secrets table (references to secrets that live in the cluster)
    op.create_table(
        'k8s_secrets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=253), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # Create datasets table
    op.create_table(
        'datasets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('k8s_secret_name', sa.String(length=253), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('host', sa.String(length=256), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default=sa.literal_column('5432')),
        sa.Column('read_schema', sa.String(length=256), nullable=True),
        sa.Column('write_schema', sa.String(length=256), nullable=True),
        sa.Column('type', sa.String(length=256), nullable=False, server_default='postgres'),
        sa.Column('extra_connection_args', sa.String(length=4096), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['k8s_secret_name'], ['k8s_secrets.name'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # Create trigger_repositories table
    op.create_table(
        'trigger_repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('api_uri', sa.String(length=4096), nullable=False),
        sa.Column('k8s_secret_name', sa.String(length=253), nullable=False),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False, server_default='main'),
        sa.Column('initial_cursor', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['k8s_secret_name'], ['k8s_secrets.name'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uri'),
    )

    # Create task_status enum table (if needed)
    op.create_table(
        'task_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create requests table (Data Access Requests - separate from the api_requests trigger)
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

    # Create triggers table (why a task ran; joined-table parent of pull_requests and api_requests)
    op.create_table(
        'triggers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False, server_default='UNKNOWN'),
        sa.Column('reason', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "(state IN ('IGNORED', 'REJECTED')) = (reason IS NOT NULL)",
            name='ck_triggers_reason_for_ignored_rejected',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_triggers_state', 'triggers', ['state'])

    # Create pull_requests table (a trigger)
    op.create_table(
        'pull_requests',
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('trigger_repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('raised_by', sa.String(length=256), nullable=False),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('merged_at', sa.DateTime(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['trigger_id'], ['triggers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trigger_repository_id'], ['trigger_repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('trigger_id'),
        sa.UniqueConstraint('trigger_repository_id', 'number', name='uq_pr_repo_number'),
    )

    # Create api_requests table (a trigger)
    op.create_table(
        'api_requests',
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=256), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.ForeignKeyConstraint(['trigger_id'], ['triggers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('trigger_id'),
    )

    # Create tasks table
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('docker_image', sa.String(length=256), nullable=False),
        sa.Column('status', sa.String(length=256), nullable=False, server_default='PENDING'),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('requested_by', sa.String(length=256), nullable=False),
        sa.Column('dagster_run_id', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('params', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['request_id'], ['requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['trigger_id'], ['triggers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dagster_run_id'),
        sa.UniqueConstraint('trigger_id'),
    )
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])
    op.create_index('ix_tasks_dataset_status', 'tasks', ['dataset_id', 'status'])
    op.create_index('ix_tasks_requested_by', 'tasks', ['requested_by'])
    op.create_index('ix_tasks_docker_image', 'tasks', ['docker_image'])
    op.create_index('ix_tasks_status_project', 'tasks', ['status', 'project_id'])

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
    op.drop_index('ix_tasks_project_id', 'tasks')
    op.drop_table('tasks')
    op.drop_table('results_backends')
    op.drop_table('requests')
    op.drop_table('task_statuses')
    op.drop_table('api_requests')
    op.drop_table('pull_requests')
    op.drop_index('ix_triggers_state', 'triggers')
    op.drop_table('triggers')
    op.drop_table('trigger_repositories')
    op.drop_table('datasets')
    op.drop_table('k8s_secrets')
    op.drop_index('ix_projects_id', 'projects')
    op.drop_table('projects')
    op.drop_table('results_repositories')
    op.drop_table('audit')
