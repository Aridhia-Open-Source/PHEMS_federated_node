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

    # Create projects table
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('default_dataset_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # Create secrets table (references to secrets that live in a secret store)
    op.create_table(
        'secrets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=253), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('provider', sa.Enum('K8S', name='secretprovidertype'), nullable=False),
        sa.Column('key', sa.String(length=253), nullable=False),
        sa.Column('namespace', sa.String(length=253), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'label'),
        sa.UniqueConstraint('project_id', 'id'),
        sa.UniqueConstraint('key'),
    )

    # Create datasets table
    op.create_table(
        'datasets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('host', sa.String(length=256), nullable=False),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('read_schema', sa.String(length=256), nullable=True),
        sa.Column('write_schema', sa.String(length=256), nullable=True),
        sa.Column('type', sa.String(length=256), nullable=False, server_default='postgres'),
        sa.Column('extra_connection_args', sa.String(length=4096), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['project_id', 'secret_id'], ['secrets.project_id', 'secrets.id'], ondelete='RESTRICT'
        ),
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
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False, server_default='main'),
        sa.Column('initial_cursor', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['project_id', 'secret_id'], ['secrets.project_id', 'secrets.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'uri', name='uq_trigger_repositories_project_uri'),
    )

    # Create results_repositories table
    op.create_table(
        'results_repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('api_uri', sa.String(length=4096), nullable=False),
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.Column('target_dir', sa.String(length=4096), nullable=False),
        sa.Column('owned_by_federated_node', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['project_id', 'secret_id'], ['secrets.project_id', 'secrets.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', name='uq_results_repositories_project'),
        sa.UniqueConstraint('project_id', 'uri', name='uq_results_repositories_project_uri'),
    )

    # Create dars table (Data Access Requests - separate from the api_requests trigger)
    op.create_table(
        'dars',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('requested_by', sa.String(length=256), nullable=False),
        sa.Column('project_name', sa.String(length=256), nullable=False),
        sa.Column('status', sa.String(length=256), nullable=True),
        sa.Column('proj_start', sa.DateTime(timezone=False), nullable=False),
        sa.Column('proj_end', sa.DateTime(timezone=False), nullable=False),
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
        sa.Column('state_cause', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "(state IN ('IGNORED', 'REJECTED')) = (state_cause IS NOT NULL)",
            name='ck_triggers_state_cause_for_ignored_rejected',
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
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('docker_image', sa.String(length=256), nullable=False),
        sa.Column('status', sa.String(length=256), nullable=True),
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

    # Create task_results table
    op.create_table(
        'task_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('results_repository_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('branch', sa.String(length=256), nullable=True),
        sa.Column('commit_sha', sa.String(length=40), nullable=True),
        sa.Column('pull_request_number', sa.Integer(), nullable=True),
        sa.Column('pull_request_url', sa.String(length=4096), nullable=True),
        sa.Column('error', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['results_repository_id'], ['results_repositories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'results_repository_id', name='uq_task_results_task_repository'),
    )

    # Create registries table
    op.create_table(
        'registries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=256), nullable=False),
        sa.Column('needs_auth', sa.Boolean(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create whitelisted_images table
    op.create_table(
        'whitelisted_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('registry_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('tag', sa.String(length=256), nullable=True),
        sa.Column('sha', sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(['registry_id'], ['registries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create catalogues table
    op.create_table(
        'catalogues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.String(length=256), nullable=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('title', 'dataset_id'),
    )

    # Create dictionaries table
    op.create_table(
        'dictionaries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('table_name', sa.String(length=256), nullable=False),
        sa.Column('field_name', sa.String(length=256), nullable=False),
        sa.Column('label', sa.String(length=256), nullable=True),
        sa.Column('description', sa.String(length=4096), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('table_name', 'dataset_id', 'field_name'),
    )

    # Add the circular FK from projects to datasets, as the model declares it
    op.create_foreign_key('fk_projects_default_dataset', 'projects', 'datasets',
                          ['default_dataset_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    # The projects <-> datasets cycle first, then the tables in reverse order
    op.drop_constraint('fk_projects_default_dataset', 'projects', type_='foreignkey')
    op.drop_table('dictionaries')
    op.drop_table('catalogues')
    op.drop_table('whitelisted_images')
    op.drop_table('registries')
    op.drop_table('task_results')
    op.drop_table('tasks')
    op.drop_table('api_requests')
    op.drop_table('pull_requests')
    op.drop_index('ix_triggers_state', 'triggers')
    op.drop_table('triggers')
    op.drop_table('results_backends')
    op.drop_table('dars')
    op.drop_table('results_repositories')
    op.drop_table('trigger_repositories')
    op.drop_table('datasets')
    op.drop_table('secrets')
    sa.Enum(name='secretprovidertype').drop(op.get_bind())
    op.drop_table('projects')
    op.drop_table('audit')
