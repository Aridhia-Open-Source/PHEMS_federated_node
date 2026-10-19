"""
Pull requests are stored once per global trigger repository and every project that watches
the repository gets a trigger for each one it should evaluate (ADR 0011).

- `store_pull_request` upserts the provider's facts. The unique constraint decides, so two
  concurrent posts of one pull request store it once.
- `fan_out` creates the triggers of newly stored pull requests for the assignments that accept triggers
  (active, and their project enabled).
- `skip_gap` moves the assignments' cursor to now when they become active again (a link enabled
  or un-revoked; its project, repository or provider switched back on),
  so what was merged while they were inactive is stored but gets no trigger.
- `backfill` is the other choice when a project is enabled: the cursor stays and the triggers
  the project missed while it was disabled are created.

Triggers are created through `create_triggers`, so a pair (assignment, pull request) gets one
trigger; the unique constraint settles a race.

Matching is decided here from stored data alone, with the rule of `spec_files`: a file the
pull request adds, ending in `.json`, under the assignment's `watch_dir`. The trigger exposes
those paths as `spec_files` and Dagster's evaluate step trusts them. A pull request that does
not match gets no trigger for that assignment; the cause is logged at info level.
"""
import logging
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.dtos.trigger_repository import PullRequestRequest
from app.helpers.base_model import db
from app.helpers.spec_files import spec_files
from app.models.project_trigger_repository import ProjectTriggerRepository, now_ts
from app.models.pull_request import PullRequest, PullRequestFile
from app.models.pull_request_trigger import PullRequestTrigger

logger = logging.getLogger('pull_request_fanout')
logger.setLevel(logging.INFO)
session = db.session


def unmatched_cause(assignment: ProjectTriggerRepository, pull_request: PullRequest) -> str | None:
    """
    Why the pull request is not for the assignment, or None when it is. A pull request whose
    changed files were truncated at the provider's cap may touch anything, so it matches.
    """
    if pull_request.base_branch != assignment.base_branch:
        return f"Pull request was merged into {pull_request.base_branch}, not {assignment.base_branch}"
    if pull_request.files_truncated:
        return None
    if spec_files(pull_request, assignment.watch_dir):
        return None
    return f"No new spec file under {assignment.watch_dir}"


def store_pull_request(
    trigger_repository_id: int, number: int, title: str, raised_by: str, merged_at: datetime,
    merge_commit_sha: str, base_branch: str, files_truncated: bool, changed_files: list[dict]
) -> tuple[PullRequest, bool]:
    """
    Stores the pull request's facts unless the repository already has that number, and returns
    it with whether this call stored it. The facts of a stored pull request are not changed.
    `changed_files` is a list of {"path", "status"}.
    """
    stored_id = session.execute(
        pg_insert(PullRequest).values(
            trigger_repository_id=trigger_repository_id, number=number, title=title, raised_by=raised_by,
            merged_at=merged_at, merge_commit_sha=merge_commit_sha, base_branch=base_branch,
            files_truncated=files_truncated,
        ).on_conflict_do_nothing(constraint='uq_pull_requests_repo_number').returning(PullRequest.id)
    ).scalar_one_or_none()

    if stored_id is None:
        existing = PullRequest.query.filter_by(trigger_repository_id=trigger_repository_id, number=number).one()
        return existing, False

    if changed_files:
        session.execute(
            sa.insert(PullRequestFile),
            [{"pull_request_id": stored_id, "path": f["path"], "status": f["status"]} for f in changed_files],
        )
    return session.get(PullRequest, stored_id), True


def ingest_pull_requests(
    trigger_repository_id: int, requests: list[PullRequestRequest]
) -> tuple[list[PullRequest], list[PullRequest]]:
    """
    Stores the pull requests and creates their triggers for every active assignment of the
    repository. Returns the pull requests stored by this call and those already stored, and
    leaves the commit to the caller. Posting the same pull requests again changes nothing.
    """
    created, existing = [], []
    for request in requests:
        pull_request, is_new = store_pull_request(
            trigger_repository_id, request.number, request.title, request.raised_by, request.merged_at,
            request.merge_commit_sha, request.base_branch, request.files_truncated,
            [f.model_dump() for f in request.changed_files],
        )
        (created if is_new else existing).append(pull_request)
    fan_out(created, active_assignments(trigger_repository_id))
    return created, existing


def active_assignments(trigger_repository_id: int) -> list[ProjectTriggerRepository]:
    """The repository's links that accept a trigger now, see `ProjectTriggerRepository.accepts_triggers`."""
    assignments = ProjectTriggerRepository.query.filter_by(
        trigger_repository_id=trigger_repository_id
    ).order_by(ProjectTriggerRepository.id)
    return [a for a in assignments if a.accepts_triggers]


def create_triggers(assignment: ProjectTriggerRepository, pull_request_ids: list[int] | None = None) -> int:
    """
    Creates the assignment's missing triggers, for the pull requests of its repository at
    or after its cursor, and returns how many. The cursor is the pair (merged_at, number): a
    pull request is in scope when it sorts after (initial_cursor, initial_cursor_number),
    so two merged in the same second are told apart by number. With `pull_request_ids` only
    those are considered.
    """
    cursor_at = assignment.initial_cursor
    cursor_number = assignment.initial_cursor_number
    has_trigger = sa.exists().where(
        PullRequestTrigger.__table__.c.pull_request_id == PullRequest.id,
        PullRequestTrigger.__table__.c.project_trigger_repository_id == assignment.id,
    )
    query = PullRequest.query.options(selectinload(PullRequest.files)).filter(
        PullRequest.trigger_repository_id == assignment.trigger_repository_id,
        sa.or_(
            PullRequest.merged_at > cursor_at,
            sa.and_(PullRequest.merged_at == cursor_at, PullRequest.number > cursor_number),
        ),
        ~has_trigger,
    )
    if pull_request_ids is not None:
        query = query.filter(PullRequest.id.in_(pull_request_ids))

    created = 0
    for pull_request in query.order_by(PullRequest.merged_at, PullRequest.number):
        cause = unmatched_cause(assignment, pull_request)
        if cause:
            logger.info("No trigger for pull request #%s in assignment %s: %s", pull_request.number, assignment.id, cause)
            continue
        trigger = PullRequestTrigger(assignment.project_id, assignment.id, pull_request.id)
        try:
            # A savepoint, so losing the race to another writer undoes only this trigger
            with session.begin_nested():
                trigger.add(commit=False)
        except IntegrityError:
            continue
        created += 1
    return created


def fan_out(pull_requests: list[PullRequest], assignments: list[ProjectTriggerRepository]) -> int:
    """Creates the triggers of newly stored pull requests for the given active assignments."""
    ids = [pr.id for pr in pull_requests]
    return sum(create_triggers(assignment, ids) for assignment in assignments)


def backfill(assignments: list[ProjectTriggerRepository]) -> int:
    """
    Creates the triggers the assignments missed while their project was disabled, for the
    ones that accept triggers now, and returns how many. The cursor is not moved, so what
    was merged before it stays without a trigger. Leaves the commit to the caller.
    """
    return sum(create_triggers(assignment) for assignment in assignments if assignment.accepts_triggers)


def skip_gap(assignments: list[ProjectTriggerRepository]) -> None:
    """
    Moves the cursor of the assignments to now (a naive UTC time like the column), for a link
    enabled or un-revoked, or its project, global repository or provider switched back on: the pull requests
    merged while it was inactive are still stored by the sensor's catch-up, but sort before the
    cursor and get no trigger. Leaves the commit to the caller.
    """
    now = now_ts().replace(tzinfo=None)
    for assignment in assignments:
        assignment.initial_cursor = now
        assignment.initial_cursor_number = 0
