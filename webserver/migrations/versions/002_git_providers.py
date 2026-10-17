"""Git providers, global: repositories name one and their path on it, instead of a uri.

Revision ID: 002_git_providers
Revises: 001_baseline
Create Date: 2026-10-17 00:00:00.000000

"""
from urllib.parse import urlparse

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_git_providers'
down_revision = '001_baseline'
branch_labels = None
depends_on = None

REPOSITORY_TABLES = ('trigger_repositories', 'results_repositories')


def upgrade() -> None:
    op.create_table(
        'git_providers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=253), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('api_uri', sa.String(length=4096), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('uri'),
    )

    for table in REPOSITORY_TABLES:
        op.add_column(table, sa.Column('provider_id', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('repo_path', sa.String(length=512), nullable=True))

    # One provider per distinct (type, scheme and host) of the existing repositories. The scheme
    # is the api_uri's, as the clone URL took it, and the api_uri that of the first repository.
    bind = op.get_bind()
    providers = {}
    for table in REPOSITORY_TABLES:
        for id, uri, provider, api_uri in bind.execute(
            sa.text(f"SELECT id, uri, provider, api_uri FROM {table} ORDER BY id")
        ).fetchall():
            host = uri.split('/')[0]
            provider_uri = f"{urlparse(api_uri).scheme}://{host}"
            if (provider, provider_uri) not in providers:
                providers[(provider, provider_uri)] = bind.execute(
                    sa.text(
                        "INSERT INTO git_providers (name, type, uri, api_uri) "
                        "VALUES (:name, :type, :uri, :api_uri) RETURNING id"
                    ),
                    {"name": f"{provider}-{host}", "type": provider, "uri": provider_uri, "api_uri": api_uri},
                ).scalar_one()
            bind.execute(
                sa.text(f"UPDATE {table} SET provider_id = :provider_id, repo_path = :repo_path WHERE id = :id"),
                {
                    "provider_id": providers[(provider, provider_uri)],
                    "repo_path": '/'.join(uri.split('/')[-2:]),
                    "id": id,
                },
            )

    for table in REPOSITORY_TABLES:
        op.alter_column(table, 'provider_id', nullable=False)
        op.alter_column(table, 'repo_path', nullable=False)
        op.create_foreign_key(
            f'fk_{table}_provider_id', table, 'git_providers', ['provider_id'], ['id'], ondelete='RESTRICT'
        )
        op.create_unique_constraint(f'uq_{table}_provider_repo_path', table, ['provider_id', 'repo_path'])
        op.drop_constraint(f'uq_{table}_uri', table, type_='unique')
        op.drop_column(table, 'uri')
        op.drop_column(table, 'provider')
        op.drop_column(table, 'api_uri')


def downgrade() -> None:
    for table in REPOSITORY_TABLES:
        op.add_column(table, sa.Column('uri', sa.String(length=4096), nullable=True))
        op.add_column(table, sa.Column('provider', sa.String(length=16), nullable=True))
        op.add_column(table, sa.Column('api_uri', sa.String(length=4096), nullable=True))
        # The uri had no scheme
        op.execute(
            f"UPDATE {table} SET uri = regexp_replace(p.uri, '^https?://', '') || '/' || {table}.repo_path, "
            f"provider = p.type, api_uri = p.api_uri "
            f"FROM git_providers p WHERE p.id = {table}.provider_id"
        )
        op.alter_column(table, 'uri', nullable=False)
        op.alter_column(table, 'provider', nullable=False)
        op.alter_column(table, 'api_uri', nullable=False)
        op.create_unique_constraint(f'uq_{table}_uri', table, ['uri'])
        op.drop_constraint(f'uq_{table}_provider_repo_path', table, type_='unique')
        op.drop_constraint(f'fk_{table}_provider_id', table, type_='foreignkey')
        op.drop_column(table, 'provider_id')
        op.drop_column(table, 'repo_path')

    op.drop_table('git_providers')
