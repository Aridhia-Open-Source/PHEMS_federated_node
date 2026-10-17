"""A repository's pull requests are unique by merge commit sha as well as by number.

Revision ID: 003_pr_merge_sha_unique
Revises: 002_git_providers
Create Date: 2026-10-17 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '003_pr_merge_sha_unique'
down_revision = '002_git_providers'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_pull_requests_repo_merge_commit_sha', 'pull_requests', ['trigger_repository_id', 'merge_commit_sha']
    )


def downgrade() -> None:
    op.drop_constraint('uq_pull_requests_repo_merge_commit_sha', 'pull_requests', type_='unique')
