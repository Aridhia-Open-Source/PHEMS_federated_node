from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy import orm

from app.models.trigger import Trigger


class PullRequestTrigger(Trigger):
    """
    A pull request merged to a watched repository, the trigger of a task. Only merged pull
    requests are watched.
    Not to be confused with `PullRequestResult`, the pull request we open to deliver results.
    The PR's facts are the shared `PullRequest`. Stores `spec_raw` (the spec file as read) for async processing by Dagster.
    `state`, `state_cause` and `project_id` are columns of the Trigger it extends.
    """
    __tablename__ = 'pull_request_triggers'
    __mapper_args__ = {'polymorphic_identity': 'PR'}
    __table_args__ = (
        sa.UniqueConstraint(
            'project_trigger_repository_id', 'pull_request_id', name='uq_pr_triggers_assignment_pull_request'
        ),
    )

    trigger_id = sa.Column(
        sa.Integer, sa.ForeignKey('triggers.id', ondelete='CASCADE'), primary_key=True
    )
    spec_raw = sa.Column(sa.Text, nullable=True)

    # RESTRICT: a pull request with triggers is not deleted from under them
    pull_request_id = sa.Column(
        sa.Integer, sa.ForeignKey('pull_requests.id', ondelete='RESTRICT'), nullable=False
    )
    # RESTRICT: an assignment with pull requests cannot be deleted from under their triggers
    project_trigger_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('project_trigger_repositories.id', ondelete='RESTRICT'),
        nullable=False
    )

    pull_request = orm.relationship("PullRequest")
    project_trigger_repository = orm.relationship(
        "ProjectTriggerRepository", back_populates="pull_request_triggers"
    )

    def __init__(self, project_id: int, project_trigger_repository_id: int, pull_request_id: int):
        super().__init__(project_id)
        self.project_trigger_repository_id = project_trigger_repository_id
        self.pull_request_id = pull_request_id

    @property
    def trigger_repository_id(self) -> int:
        """The global repository, which is how the API addresses the project's link to it."""
        return self.project_trigger_repository.trigger_repository_id

    @property
    def number(self) -> int:
        return self.pull_request.number

    @property
    def title(self) -> str:
        return self.pull_request.title

    @property
    def raised_by(self) -> str:
        return self.pull_request.raised_by

    @property
    def merge_commit_sha(self) -> str:
        return self.pull_request.merge_commit_sha

    @property
    def merged_at(self) -> dt:
        return self.pull_request.merged_at

    @property
    def requested_by(self) -> str:
        return self.raised_by

    def __repr__(self):
        return f'<PullRequestTrigger (assignment_id={self.project_trigger_repository_id}, pr={self.number})>'
