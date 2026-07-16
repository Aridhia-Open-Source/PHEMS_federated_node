"""Repository table migration

Moves the `repository` string column on `datasets` into a normalised
`repositories` table, replacing the column with a nullable FK.

Revision ID: f3a8b9c2d1e4
Revises: a18ca22994f6
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a8b9c2d1e4'
down_revision: Union[str, None] = 'a18ca22994f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('uri', sa.String(length=4096), nullable=False),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), nullable=False, server_default='main'),
        sa.Column('polled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uri')
    )

    op.add_column('datasets', sa.Column('repository_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_datasets_repository_id',
        'datasets', 'repositories',
        ['repository_id'], ['id']
    )

    conn = op.get_bind()
    datasets = conn.execute(
        sa.text("SELECT id, repository FROM datasets WHERE repository IS NOT NULL")
    ).fetchall()

    for dataset_id, repository_uri in datasets:
        existing = conn.execute(
            sa.text("SELECT id FROM repositories WHERE uri = :uri"),
            {"uri": repository_uri.lower()}
        ).fetchone()

        if existing:
            repo_id = existing[0]
        else:
            conn.execute(
                sa.text("INSERT INTO repositories (uri) VALUES (:uri)"),
                {"uri": repository_uri.lower()}
            )
            repo_result = conn.execute(
                sa.text("SELECT id FROM repositories WHERE uri = :uri"),
                {"uri": repository_uri.lower()}
            ).fetchone()
            repo_id = repo_result[0] if repo_result else None

        conn.execute(
            sa.text("UPDATE datasets SET repository_id = :rid WHERE id = :did"),
            {"rid": repo_id, "did": dataset_id}
        )

    op.drop_column('datasets', 'repository')


def downgrade() -> None:
    op.add_column('datasets', sa.Column('repository', sa.String(length=4096), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT d.id, r.uri FROM datasets d "
            "JOIN repositories r ON d.repository_id = r.id "
            "WHERE d.repository_id IS NOT NULL"
        )
    ).fetchall()

    for dataset_id, uri in rows:
        conn.execute(
            sa.text("UPDATE datasets SET repository = :uri WHERE id = :did"),
            {"uri": uri, "did": dataset_id}
        )

    op.drop_constraint('fk_datasets_repository_id', 'datasets', type_='foreignkey')
    op.drop_column('datasets', 'repository_id')
    op.drop_table('repositories')
