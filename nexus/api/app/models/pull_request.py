"""
A pull request merged to a global trigger repository: the provider's facts, stored once however
many projects watch the repository. What a project makes of it (state, spec, task) is its
`PullRequestTrigger`, created for each project that watches the repository (ADR 0011, see
`TriggerRepository.ingest` and `ProjectTriggerRepository.create_triggers`).
"""
import logging
from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import validates

from app.database.base_model import BaseModel, db

logger = logging.getLogger('pull_request_model')
logger.setLevel(logging.INFO)


class PullRequest(db.Model, BaseModel):
    __tablename__ = 'pull_requests'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    trigger_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('trigger_repositories.id', ondelete='CASCADE'), nullable=False
    )
    number = sa.Column(sa.Integer, nullable=False)
    title = sa.Column(sa.String(256), nullable=False)
    raised_by = sa.Column(sa.String(256), nullable=False)
    merge_commit_sha = sa.Column(sa.String(40), nullable=False)
    merged_at = sa.Column(sa.DateTime(timezone=False), nullable=False)
    # The branch the pull request was merged into
    base_branch = sa.Column(sa.String(256), nullable=False)
    # The provider caps the changed files it lists. Past the cap the list is incomplete, so the
    # pull request is taken to touch every path.
    files_truncated = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.UniqueConstraint('trigger_repository_id', 'number', name='uq_pull_requests_repo_number'),
        # The same merge can't be stored twice under different numbers on one base branch; a fast-forward
        # or rebase merge can give two base branches the same commit
        sa.UniqueConstraint(
            'trigger_repository_id', 'base_branch', 'merge_commit_sha',
            name='uq_pull_requests_repo_base_branch_merge_commit_sha'
        ),
        sa.Index('ix_pull_requests_repo_merged_at_number', 'trigger_repository_id', 'merged_at', 'number'),
    )

    files = orm.relationship(
        "PullRequestFile", back_populates="pull_request", cascade="all, delete-orphan", passive_deletes=True
    )

    @validates('merged_at')
    def validate_merged_at(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                return dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("merged_at must be a valid ISO 8601 datetime string")
        return value

    @classmethod
    def store(
        cls, trigger_repository_id: int, number: int, title: str, raised_by: str, merged_at: dt,
        merge_commit_sha: str, base_branch: str, files_truncated: bool, changed_files: list[dict]
    ) -> tuple["PullRequest", bool]:
        """
        Stores the pull request's facts unless the repository already has that number, or already has
        that merge commit on the same base branch under another number, and returns the stored row
        with whether this call stored it. The facts of a stored pull request are not changed. The unique
        constraints decide, so two concurrent posts of one pull request store it once. A pull request whose merge
        commit is already stored under another number for the same base branch is skipped with a warning.
        `changed_files` is a list of {"path", "status"}.
        """
        stored_id = db.session.execute(
            pg_insert(cls).values(
                trigger_repository_id=trigger_repository_id, number=number, title=title, raised_by=raised_by,
                merged_at=merged_at, merge_commit_sha=merge_commit_sha, base_branch=base_branch,
                files_truncated=files_truncated,
            ).on_conflict_do_nothing().returning(cls.id)
        ).scalar_one_or_none()

        if stored_id is None:
            existing = cls.query.filter_by(trigger_repository_id=trigger_repository_id, number=number).first()
            if existing is None:
                existing = cls.query.filter_by(
                    trigger_repository_id=trigger_repository_id, base_branch=base_branch,
                    merge_commit_sha=merge_commit_sha
                ).first()
                if existing is None:
                    raise RuntimeError(
                        f"Pull request #{number} was not stored and no stored pull request conflicts with it"
                    )
                logger.warning(
                    "Pull request #%s skipped: #%s already has merge commit %s on %s",
                    number, existing.number, merge_commit_sha, base_branch,
                )
            return existing, False

        if changed_files:
            db.session.execute(
                sa.insert(PullRequestFile),
                [{"pull_request_id": stored_id, "path": f["path"], "status": f["status"]} for f in changed_files],
            )
        return db.session.get(cls, stored_id), True

    def __repr__(self):
        return f'<PullRequest (repository_id={self.trigger_repository_id}, pr={self.number})>'


class PullRequestFile(db.Model, BaseModel):
    """
    A file a pull request changed: its path and how (`added`, `modified`...). Only the path
    and status are kept, never content. The status is kept because a spec is a file the pull
    request adds.
    """
    __tablename__ = 'pull_request_files'

    pull_request_id = sa.Column(
        sa.Integer, sa.ForeignKey('pull_requests.id', ondelete='CASCADE'), primary_key=True
    )
    path = sa.Column(sa.String(1024), primary_key=True)
    status = sa.Column(sa.String(32), nullable=False)

    pull_request = orm.relationship("PullRequest", back_populates="files")
