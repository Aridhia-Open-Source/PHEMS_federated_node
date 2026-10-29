"""Baseline schema.

The only migration until release: a branch that changes the schema regenerates this file
(`python -m alembic revision --autogenerate`, against an empty database, keeping revision id
001_baseline) instead of adding 002+.

Revision ID: 001_baseline
Revises:
Create Date: 2026-10-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def _unique_when_live(name: str, table: str, columns: list[str]) -> None:
    """A unique index a soft-deleted row is free of, so a re-created resource can take its name."""
    op.create_index(name, table, columns, unique=True, postgresql_where=sa.text('deleted_at IS NULL'))


def upgrade() -> None:
    op.create_table('git_providers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=253), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('api_uri', sa.String(length=4096), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_git_providers_name', 'git_providers', ['name'])
    _unique_when_live('uq_git_providers_uri', 'git_providers', ['uri'])
    op.create_table('secrets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('label', sa.String(length=253), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('provider', sa.Enum('K8S', name='secretprovidertype'), nullable=False),
        sa.Column('key', sa.String(length=253), nullable=False),
        sa.Column('namespace', sa.String(length=253), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_secrets_key', 'secrets', ['key'])
    _unique_when_live('uq_secrets_label', 'secrets', ['label'])
    op.create_table('datasets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('host', sa.String(length=256), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('read_schema', sa.String(length=256), nullable=True),
        sa.Column('write_schema', sa.String(length=256), nullable=True),
        sa.Column('type', sa.String(length=256), server_default='postgres', nullable=False),
        sa.Column('extra_connection_args', sa.String(length=4096), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['secret_id'], ['secrets.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_datasets_name', 'datasets', ['name'])
    op.create_table('results_repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('repo_path', sa.String(length=512), nullable=False),
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['provider_id'], ['git_providers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['secret_id'], ['secrets.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_results_repositories_provider_repo_path', 'results_repositories', ['provider_id', 'repo_path'])
    op.create_table('trigger_repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('repo_path', sa.String(length=512), nullable=False),
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['provider_id'], ['git_providers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['secret_id'], ['secrets.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_trigger_repositories_provider_repo_path', 'trigger_repositories', ['provider_id', 'repo_path'])
    op.create_table('catalogues',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.String(length=256), nullable=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('title', 'dataset_id')
    )
    op.create_table('dictionaries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('table_name', sa.String(length=256), nullable=False),
        sa.Column('field_name', sa.String(length=256), nullable=False),
        sa.Column('label', sa.String(length=256), nullable=True),
        sa.Column('description', sa.String(length=4096), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('table_name', 'dataset_id', 'field_name')
    )
    op.create_table('projects',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=4096), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('default_dataset_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['default_dataset_id'], ['datasets.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_projects_name', 'projects', ['name'])
    op.create_table('pull_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trigger_repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('raised_by', sa.String(length=256), nullable=False),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=False),
        sa.Column('merged_at', sa.DateTime(), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False),
        sa.Column('files_truncated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.ForeignKeyConstraint(['trigger_repository_id'], ['trigger_repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trigger_repository_id', 'base_branch', 'merge_commit_sha', name='uq_pull_requests_repo_base_branch_merge_commit_sha'),
        sa.UniqueConstraint('trigger_repository_id', 'number', name='uq_pull_requests_repo_number')
    )
    op.create_index('ix_pull_requests_repo_merged_at_number', 'pull_requests', ['trigger_repository_id', 'merged_at', 'number'], unique=False)
    op.create_table('task_specs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('image', sa.String(length=256), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('env', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('compute', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('tags', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('project_datasets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_project_datasets_project_dataset', 'project_datasets', ['project_id', 'dataset_id'])
    op.create_table('project_results_repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('results_repository_id', sa.Integer(), nullable=False),
        sa.Column('target_dir', sa.String(length=4096), nullable=False),
        sa.Column('owned_by_federated_node', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['results_repository_id'], ['results_repositories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_project_results_repositories_project', 'project_results_repositories', ['project_id'])
    op.create_table('project_secrets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('secret_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['secret_id'], ['secrets.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_project_secrets_project_secret', 'project_secrets', ['project_id', 'secret_id'])
    op.create_table('project_trigger_repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('trigger_repository_id', sa.Integer(), nullable=False),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False),
        sa.Column('initial_cursor', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('initial_cursor_number', sa.Integer(), server_default='0', nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['trigger_repository_id'], ['trigger_repositories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    _unique_when_live('uq_project_trigger_repositories_project_repo', 'project_trigger_repositories', ['project_id', 'trigger_repository_id'])
    op.create_table('pull_request_files',
        sa.Column('pull_request_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(length=1024), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('pull_request_id', 'path')
    )
    op.create_table('results_backends',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=16), server_default='git', nullable=False),
        sa.Column('config', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id')
    )
    op.create_table('triggers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=32), server_default='UNKNOWN', nullable=False),
        sa.Column('state_cause', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("(state = 'REJECTED') = (state_cause IS NOT NULL)", name='ck_triggers_state_cause_for_rejected'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_triggers_state', 'triggers', ['state'], unique=False)
    op.create_table('api_request_triggers',
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=256), nullable=False),
        sa.Column('spec_raw', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['trigger_id'], ['triggers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('trigger_id')
    )
    op.create_table('pull_request_triggers',
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('spec_raw', sa.Text(), nullable=True),
        sa.Column('pull_request_id', sa.Integer(), nullable=False),
        sa.Column('project_trigger_repository_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['project_trigger_repository_id'], ['project_trigger_repositories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['trigger_id'], ['triggers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('trigger_id'),
        sa.UniqueConstraint('project_trigger_repository_id', 'pull_request_id', name='uq_pr_triggers_assignment_pull_request')
    )
    op.create_table('tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('trigger_id', sa.Integer(), nullable=False),
        sa.Column('task_spec_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('status', sa.String(length=256), nullable=True),
        sa.Column('attempt', sa.Integer(), server_default='1', nullable=False),
        sa.Column('requested_by', sa.String(length=256), nullable=False),
        sa.Column('executor_run_id', sa.String(length=64), nullable=True),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('state_cause', sa.Text(), nullable=True),
        sa.Column('config_snapshot', sa.JSON(), nullable=True),
        sa.Column('config_hash', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('params', sa.JSON(), server_default='{}', nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['task_spec_id'], ['task_specs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['trigger_id'], ['triggers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('executor_run_id'),
        sa.UniqueConstraint('trigger_id')
    )
    op.create_index(op.f('ix_tasks_project_id'), 'tasks', ['project_id'], unique=False)
    op.create_index('ix_tasks_requested_by', 'tasks', ['requested_by'], unique=False)
    op.create_index('ix_tasks_status_project', 'tasks', ['status', 'project_id'], unique=False)
    op.create_table('results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('results_repository_id', sa.Integer(), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['results_repository_id'], ['project_results_repositories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'results_repository_id', name='uq_results_task_repository')
    )
    op.create_table('pull_request_results',
        sa.Column('result_id', sa.Integer(), nullable=False),
        sa.Column('step', sa.String(length=32), server_default='UNKNOWN', nullable=False),
        sa.Column('state', sa.String(length=32), server_default='IN_PROGRESS', nullable=False),
        sa.Column('branch', sa.String(length=256), nullable=True),
        sa.Column('commit_sha', sa.String(length=40), nullable=True),
        sa.Column('number', sa.Integer(), nullable=True),
        sa.Column('url', sa.String(length=4096), nullable=True),
        sa.Column('merged_at', sa.DateTime(), nullable=True),
        sa.Column('merge_commit_sha', sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(['result_id'], ['results.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('result_id')
    )


def downgrade() -> None:
    op.drop_table('pull_request_results')
    op.drop_table('results')
    op.drop_table('tasks')
    op.drop_table('pull_request_triggers')
    op.drop_table('api_request_triggers')
    op.drop_table('triggers')
    op.drop_table('results_backends')
    op.drop_table('pull_request_files')
    op.drop_table('project_trigger_repositories')
    op.drop_table('project_secrets')
    op.drop_table('project_results_repositories')
    op.drop_table('project_datasets')
    op.drop_table('task_specs')
    op.drop_table('pull_requests')
    op.drop_table('projects')
    op.drop_table('dictionaries')
    op.drop_table('catalogues')
    op.drop_table('trigger_repositories')
    op.drop_table('results_repositories')
    op.drop_table('datasets')
    op.drop_table('secrets')
    op.drop_table('git_providers')
    sa.Enum(name='secretprovidertype').drop(op.get_bind())
