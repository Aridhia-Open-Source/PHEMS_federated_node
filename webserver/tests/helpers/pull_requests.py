from datetime import datetime

from app.helpers.base_model import db
from app.helpers.pull_request_fanout import store_pull_request
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request_trigger import PullRequestTrigger

SPEC_FILE = {"path": "spec.json", "status": "added"}


def pr_body(number=1, merged_at="2026-01-01T10:00:00Z", changed_files=(SPEC_FILE,), **fields) -> dict:
    """A pull request as the ingest posts it: its facts and the files it changed."""
    return {
        "number": number, "title": f"PR {number}", "raised_by": "user1", "merged_at": merged_at,
        "merge_commit_sha": (f"{number}" * 40)[:40], "base_branch": "main", "files_truncated": False,
        "changed_files": list(changed_files), **fields,
    }


def add_pull_request_trigger(
    assignment: ProjectTriggerRepository, number=1, merged_at="2026-01-01T10:00:00", title=None,
    raised_by="user", sha=None, **facts
) -> PullRequestTrigger:
    """Stores a pull request of the assignment's repository and gives the assignment a trigger for it."""
    body = pr_body(
        number, merged_at, title=title or f"PR {number}", raised_by=raised_by,
        merge_commit_sha=sha or "a" * 40, **facts
    )
    body["merged_at"] = datetime.fromisoformat(body["merged_at"].rstrip("Z"))
    pull_request, _ = store_pull_request(assignment.trigger_repository_id, **body)
    trigger = PullRequestTrigger(assignment.project_id, assignment.id, pull_request.id)
    trigger.add()
    return trigger
