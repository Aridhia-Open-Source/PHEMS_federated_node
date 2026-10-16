"""
Pull requests are stored once per global trigger repository and every project that watches
the repository gets a trigger for each one it should evaluate (ADR 0019).

- `store_pull_request` upserts the provider's facts. The unique constraint decides, so two
  concurrent posts of one pull request store it once.
- `fan_out` creates the triggers of newly stored pull requests for the active assignments.
- `backfill` creates the triggers an assignment missed: when it is created, enabled or
  un-revoked, or its `initial_cursor` moves earlier.

Both create triggers through `create_triggers`, so a pair (assignment, pull request) gets one
trigger however it is reached; the unique constraint settles a race.

Matching is decided here from stored data alone, with the rule the Dagster evaluate step
applies to the files of a pull request (`PullRequestParser._filter_watched_files`): a file
the pull request adds, ending in `.json`, under the assignment's `watch_dir`. A pull request
that does not match is stored as an IGNORED trigger, with the reason.
"""
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.dtos.trigger_repository import PullRequestRequest
from app.helpers.base_model import db
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request import PullRequest, PullRequestFile
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.trigger_state import TriggerState

session = db.session


def is_under_dir(filename: str, directory: str) -> bool:
    """
    Whether the file's directory is the given directory or inside it, matching whole path
    segments. An empty directory is the whole repository.
    """
    wanted = [s for s in directory.split("/") if s not in ("", ".")]
    return filename.split("/")[:-1][:len(wanted)] == wanted


def ignored_cause(assignment: ProjectTriggerRepository, pull_request: PullRequest) -> str | None:
    """
    Why the pull request is not for the assignment, or None when it is. A pull request whose
    changed files were truncated at the provider's cap may touch anything, so it matches.
    """
    if pull_request.base_branch != assignment.base_branch:
        return f"Pull request was merged into {pull_request.base_branch}, not {assignment.base_branch}"
    if pull_request.files_truncated:
        return None
    for file in pull_request.files:
        if is_under_dir(file.path, assignment.watch_dir) and file.path.endswith('.json') and file.status == "added":
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
    return ProjectTriggerRepository.query.filter(
        ProjectTriggerRepository.trigger_repository_id == trigger_repository_id,
        ProjectTriggerRepository.enabled.is_(True),
        ProjectTriggerRepository.revoked.is_(False),
    ).order_by(ProjectTriggerRepository.id).all()


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
        trigger = PullRequestTrigger(assignment.project_id, assignment.id, pull_request.id)
        cause = ignored_cause(assignment, pull_request)
        if cause:
            trigger.set_state(TriggerState.IGNORED.value, cause)
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


def backfill(assignment: ProjectTriggerRepository) -> int:
    """
    Creates the triggers the assignment missed: for a new, re-enabled or un-revoked assignment,
    or one whose initial_cursor moved earlier. Only for an active assignment.
    """
    return create_triggers(assignment)
