from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import validates

from app.helpers.exceptions import InvalidRequest
from app.models.pull_request_result_step import PullRequestResultStep
from app.models.result_state import ResultState
from app.models.result import Result

# MERGED and CLOSED are terminal and of equal rank.
STEP_RANK = {
    PullRequestResultStep.UNKNOWN.value: 0,
    PullRequestResultStep.PUSHED.value: 1,
    PullRequestResultStep.OPENED.value: 2,
    PullRequestResultStep.MERGED.value: 3,
    PullRequestResultStep.CLOSED.value: 3,
}


class PullRequestResult(Result):
    """
    A pull request we open on a results repository to deliver a task's results.
    Not to be confused with the trigger-side `PullRequestTrigger`, the merged pull request we
    watch that leads to a task.
    Columns are filled in stages as the delivery progresses: branch and commit when pushed,
    the pull request once opened, and its merge time and sha as it is synced.
    """
    __tablename__ = 'pull_request_results'
    __mapper_args__ = {'polymorphic_identity': 'PR'}

    result_id = sa.Column(
        sa.Integer, sa.ForeignKey('results.id', ondelete='CASCADE'), primary_key=True
    )
    # The furthest delivery step reached, forward only, see PullRequestResultStep.
    step = sa.Column(
        sa.String(32),
        nullable=False,
        default=PullRequestResultStep.UNKNOWN.value,
        server_default=PullRequestResultStep.UNKNOWN.value,
    )
    # How the delivery is going, see ResultState.
    state = sa.Column(
        sa.String(32),
        nullable=False,
        default=ResultState.IN_PROGRESS.value,
        server_default=ResultState.IN_PROGRESS.value,
    )
    branch = sa.Column(sa.String(256), nullable=True)
    commit_sha = sa.Column(sa.String(40), nullable=True)
    number = sa.Column(sa.Integer, nullable=True)
    url = sa.Column(sa.String(4096), nullable=True)
    merged_at = sa.Column(sa.DateTime(timezone=False), nullable=True)
    merge_commit_sha = sa.Column(sa.String(40), nullable=True)

    @validates('merged_at')
    def validate_merged_at(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                return dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("merged_at must be a valid ISO 8601 datetime string")
        return value

    def set_step(self, step: str):
        """
        Set the step, which only moves forward and nowhere once MERGED or CLOSED. Setting the
        current step again is allowed. Stops a late write, e.g. a delivery retry recording
        OPENED, from undoing what the sync sensor found.
        """
        if not isinstance(step, str) or step not in STEP_RANK:
            valid = ', '.join([s.value for s in PullRequestResultStep])
            raise InvalidRequest(f"Invalid step: {step}. Must be one of: {valid}")
        terminal = STEP_RANK[self.step] == STEP_RANK[PullRequestResultStep.MERGED.value]
        if step != self.step and (terminal or STEP_RANK[step] < STEP_RANK[self.step]):
            raise InvalidRequest(f"step cannot move from {self.step} to {step}")
        self.step = step

    def __repr__(self):
        return f'<PullRequestResult (task_id={self.task_id}, pr={self.number})>'
