"""
A project's grant of a global trigger repository, holding the project's own state for it:
which directory and branch it watches, where its pull requests start, and whether it may use it.
"""
import logging
from datetime import datetime as dt
from datetime import timezone as tz
from typing import cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, selectinload
from sqlalchemy.sql import func

from app.database.base_model import BaseModel, db
from app.database.soft_delete import SoftDeleteMixin
from app.helpers.exceptions import UnauthorizedError
from app.models import Models
from app.models.user import OwnedMixin

logger = logging.getLogger('project_trigger_repository_model')
logger.setLevel(logging.INFO)


def now_ts():
    return dt.now(tz=tz.utc)


class ProjectTriggerRepository(SoftDeleteMixin, OwnedMixin, db.Model, BaseModel):
    __tablename__ = 'project_trigger_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    trigger_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('trigger_repositories.id', ondelete='RESTRICT'), nullable=False
    )
    watch_dir = sa.Column(sa.String(4096), nullable=False)
    base_branch = sa.Column(sa.String(256), nullable=False)
    initial_cursor = sa.Column(
        sa.DateTime, nullable=False, server_default=func.now(), default=now_ts
    )
    # Where the cursor stands within initial_cursor's timestamp: the assignment starts after
    # (initial_cursor, initial_cursor_number). Both are set when the project resource is created, from the
    # latest pull request stored. 0 starts at the timestamp itself, as pull request numbers
    # begin at 1; the number of the latest pull request starts after it.
    initial_cursor_number = sa.Column(sa.Integer, nullable=False, default=0, server_default='0')
    # A person turned the repository on or off for the project
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # The controller withdrew the project's access. Never touches enabled, so a re-grant
    # restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.Index(
            'uq_project_trigger_repositories_project_repo', 'project_id', 'trigger_repository_id',
            unique=True, postgresql_where=sa.text('deleted_at IS NULL')
        ),
    )

    project = relationship("Project", back_populates="trigger_repository_assignments")
    trigger_repository = relationship("TriggerRepository", back_populates="project_assignments")
    # RESTRICT in the database, so the ORM leaves the triggers alone and the delete fails
    pull_request_triggers = relationship(
        "PullRequestTrigger", back_populates="project_trigger_repository", passive_deletes='all'
    )

    @property
    def active(self) -> bool:
        return self.trigger_repository.active and self.enabled and not self.revoked

    @property
    def accepts_triggers(self) -> bool:
        """Whether a new pull request gets a trigger for this project resource: it is active and its project is enabled and not revoked."""
        return self.active and self.project.enabled and not self.project.revoked

    def require_token_allowed(self) -> None:
        """A 403 if the project or this resource is revoked: no token for the trigger repository (ADR 0008)."""
        if self.project.revoked:
            raise UnauthorizedError(f"Project {self.project_id} is revoked")
        if self.revoked:
            raise UnauthorizedError(
                f"Repository {self.trigger_repository.uri} is revoked for project {self.project_id}"
            )

    @property
    def dataset(self):
        """
        Which dataset a PR from this repository runs against by default
        """
        return self.project.default_dataset

    @staticmethod
    def is_under_dir(filename: str, directory: str) -> bool:
        """
        Whether the file's directory is the given directory or inside it, matching whole path
        segments. An empty directory is the whole repository.
        """
        wanted = [s for s in directory.split("/") if s not in ("", ".")]
        return filename.split("/")[:-1][:len(wanted)] == wanted

    def spec_files(self, pull_request) -> list[str]:
        """
        The paths of the spec files the pull request carries for this project resource's watch_dir: files it adds,
        ending in `.json`, under the directory. The one rule of what a pull request matches,
        used by the fan-out and exposed on the trigger for Dagster's evaluate step.
        """
        return [
            file.path for file in pull_request.files
            if file.status == "added" and file.path.endswith('.json') and self.is_under_dir(file.path, self.watch_dir)
        ]

    def unmatched_cause(self, pull_request) -> str | None:
        """
        Why the pull request is not for this project resource, or None when it is. A pull request whose
        changed files were truncated at the provider's cap may touch anything, so it matches.
        """
        if pull_request.base_branch != self.base_branch:
            return f"Pull request was merged into {pull_request.base_branch}, not {self.base_branch}"
        if pull_request.files_truncated:
            return None
        if self.spec_files(pull_request):
            return None
        return f"No new spec file under {self.watch_dir}"

    def create_triggers(self, pull_request_ids: list[int] | None = None) -> int:
        """
        Creates the project resource's missing triggers, for the pull requests of its repository at
        or after its cursor, and returns how many. The cursor is the pair (merged_at, number): a
        pull request is in scope when it sorts after (initial_cursor, initial_cursor_number),
        so two merged in the same second are told apart by number. With `pull_request_ids` only
        those are considered. A pair (project resource, pull request) gets one trigger; the unique constraint
        settles a race. A pull request that does not match gets no trigger; the cause is logged at info level.
        """
        cursor_at = self.initial_cursor
        cursor_number = self.initial_cursor_number
        has_trigger = sa.exists().where(
            Models.PullRequestTrigger.__table__.c.pull_request_id == Models.PullRequest.id,
            Models.PullRequestTrigger.__table__.c.project_trigger_repository_id == self.id,
        )
        query = Models.PullRequest.query.options(selectinload(Models.PullRequest.files)).filter(
            Models.PullRequest.trigger_repository_id == self.trigger_repository_id,
            sa.or_(
                Models.PullRequest.merged_at > cursor_at,
                sa.and_(Models.PullRequest.merged_at == cursor_at, Models.PullRequest.number > cursor_number),
            ),
            ~has_trigger,
        )
        if pull_request_ids is not None:
            query = query.filter(Models.PullRequest.id.in_(pull_request_ids))

        created = 0
        for pull_request in query.order_by(Models.PullRequest.merged_at, Models.PullRequest.number):
            cause = self.unmatched_cause(pull_request)
            if cause:
                logger.info("No trigger for pull request #%s in assignment %s: %s", pull_request.number, self.id, cause)
                continue
            trigger = Models.PullRequestTrigger(self.project_id, self.id, pull_request.id)
            try:
                # A savepoint, so losing the race to another writer undoes only this trigger
                with db.session.begin_nested():
                    trigger.add(commit=False)
            except IntegrityError:
                continue
            created += 1
        return created

    @classmethod
    def backfill(cls, assignments: list["ProjectTriggerRepository"]) -> int:
        """
        Creates the triggers the assignments missed while their project was disabled, for the
        ones that accept triggers now, and returns how many. The cursor is not moved, so what
        was merged before it stays without a trigger. Leaves the commit to the caller.
        """
        return sum(assignment.create_triggers() for assignment in assignments if assignment.accepts_triggers)

    @classmethod
    def skip_gap(cls, assignments: list["ProjectTriggerRepository"]) -> None:
        """
        Moves the cursor of the assignments to now (a naive UTC time like the column), for a project
        resource enabled or un-revoked, or its project, global repository or provider switched back on: the pull
        requests merged while it was inactive are still stored by the sensor's catch-up, but sort before the
        cursor and get no trigger. Leaves the commit to the caller.
        """
        now = now_ts().replace(tzinfo=None)
        for assignment in assignments:
            assignment.initial_cursor = now
            assignment.initial_cursor_number = 0

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
        base_branch: str,
        enabled: bool = True,
        revoked: bool = False,
    ):
        self.project_id = project_id
        self.trigger_repository_id = trigger_repository_id
        self.watch_dir = watch_dir
        self.base_branch = base_branch
        self.enabled = enabled
        self.revoked = revoked

    def __repr__(self):
        return f'<ProjectTriggerRepository {self.project_id}:{self.trigger_repository_id}>'
