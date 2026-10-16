"""
A project's grant of a global trigger repository, holding the project's own state for it:
which directory and branch it watches, where its pull requests start, and whether it may use it.
"""
from datetime import datetime as dt
from datetime import timezone as tz
from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.models import Models


def now_ts():
    return dt.now(tz=tz.utc)


class ProjectTriggerRepository(db.Model, BaseModel):
    __tablename__ = 'project_trigger_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    trigger_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('trigger_repositories.id', ondelete='RESTRICT'), nullable=False
    )
    watch_dir = sa.Column(sa.String(4096), nullable=False)
    base_branch = sa.Column(sa.String(256), nullable=False, default='main')
    initial_cursor = sa.Column(
        sa.DateTime, nullable=False, server_default=func.now(), default=now_ts
    )
    # Where the cursor stands within initial_cursor's timestamp: the assignment starts after
    # (initial_cursor, initial_cursor_number). 0 starts at the timestamp itself, as pull
    # request numbers begin at 1; the number of the latest pull request starts after it.
    initial_cursor_number = sa.Column(sa.Integer, nullable=False, default=0, server_default='0')
    # A person turned the repository on or off for the project
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # The controller withdrew the project's access. Never touches enabled, so a re-grant
    # restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.UniqueConstraint(
            'project_id', 'trigger_repository_id', 'watch_dir',
            name='uq_project_trigger_repositories_project_repo_dir'
        ),
    )

    project = relationship("Project", back_populates="trigger_repository_assignments")
    trigger_repository = relationship("TriggerRepository", back_populates="project_assignments")
    # RESTRICT in the database, so the ORM leaves the triggers alone and the delete fails
    pull_request_triggers = relationship(
        "PullRequestTrigger", back_populates="project_trigger_repository", passive_deletes='all'
    )

    @validates('initial_cursor')
    def validate_initial_cursor(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                value = dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("initial_cursor must be a valid ISO 8601 datetime string")

        if self.id is not None and self.pull_request_triggers and value > self.initial_cursor:
            raise ValueError(
                "initial_cursor can only be moved earlier while pull requests exist, "
                "a later one would leave triggers before the cursor"
            )

        return value

    @property
    def active(self) -> bool:
        return self.enabled and not self.revoked

    @property
    def dataset(self):
        """
        Which dataset a PR from this repository runs against by default
        """
        return self.project.default_dataset

    def get_pull_request_cursor(self) -> str:
        """
        Get latest PR merge time from all ingested pull requests.
        If no pull requests exist, use initial_cursor as the starting point.
        """
        pr_cursor = db.session.query(func.max(Models.PullRequest.merged_at))\
            .join(Models.PullRequestTrigger, Models.PullRequestTrigger.pull_request_id == Models.PullRequest.id)\
            .filter(Models.PullRequestTrigger.project_trigger_repository_id == self.id)\
            .scalar()

        initial_cursor = cast(dt, self.initial_cursor)

        return (pr_cursor or initial_cursor).strftime("%Y-%m-%dT%H:%M:%SZ")

    def __init__(
        self,
        project_id: int,
        trigger_repository_id: int,
        watch_dir: str,
        base_branch: str = 'main',
        initial_cursor: dt | None = None,
        enabled: bool = True,
        revoked: bool = False,
    ):
        self.project_id = project_id
        self.trigger_repository_id = trigger_repository_id
        self.watch_dir = watch_dir
        self.base_branch = base_branch
        self.initial_cursor = initial_cursor
        self.enabled = enabled
        self.revoked = revoked

    def __repr__(self):
        return f'<ProjectTriggerRepository {self.project_id}:{self.trigger_repository_id}>'
