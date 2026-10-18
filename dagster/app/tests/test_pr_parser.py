import json
from unittest.mock import MagicMock

import pytest

from app.definitions.sensors.git.pr_parser import PullRequestOutcome, PullRequestParser
from app.models import PullRequestTrigger

WATCHED = "specs/a.json"


def pr(spec_files):
    return PullRequestTrigger(
        project_id=1, trigger_repository_id=1, number=5, title="t", raised_by="dev",
        merged_at="2026-01-01T00:00:00Z", merge_commit_sha="abc", state="UNKNOWN",
        spec_files=spec_files,
    )


def parse(spec_files, contents=None):
    git_api = MagicMock()
    git_api.get_file_contents.return_value = contents
    repo = MagicMock(repo_path="org/repo", watch_dir="specs/")
    return PullRequestParser(git_api, repo, MagicMock()).parse(pr(spec_files)), git_api


def test_no_spec_file_is_rejected_with_a_reason():
    parsed, git_api = parse([])

    assert parsed.outcome == PullRequestOutcome.REJECTED
    assert parsed.spec_raw is None
    assert "specs/" in parsed.state_cause
    git_api.get_file_contents.assert_not_called()


def test_several_watched_files_are_rejected_naming_them():
    files = [WATCHED, "specs/b.json"]

    parsed = parse(files)[0]

    assert parsed.outcome == PullRequestOutcome.REJECTED
    assert "specs/a.json" in parsed.state_cause and "specs/b.json" in parsed.state_cause


@pytest.mark.parametrize("contents", ["not json", json.dumps({}), json.dumps({"spec": {"env": {}}})])
def test_the_spec_file_is_passed_on_as_read_whether_or_not_it_is_valid(contents):
    """The backend parses and validates it, and keeps what was read."""
    parsed = parse([WATCHED], contents)[0]

    assert parsed.outcome == PullRequestOutcome.READY
    assert parsed.spec_raw == contents


def test_a_ready_pr_carries_the_spec_file():
    contents = json.dumps({"spec": {"docker_image": "a/b:1"}})
    parsed, git_api = parse([WATCHED], contents)

    assert parsed.outcome == PullRequestOutcome.READY
    assert parsed.state_cause is None
    assert parsed.spec_raw == contents
    git_api.get_file_contents.assert_called_once_with(repo_path="org/repo", file_path="specs/a.json", ref="abc")


def test_a_git_failure_raises_instead_of_rejecting():
    git_api = MagicMock()
    git_api.get_file_contents.side_effect = ConnectionError("git down")
    repo = MagicMock(repo_path="org/repo", watch_dir="specs/")

    with pytest.raises(ConnectionError):
        PullRequestParser(git_api, repo, MagicMock()).parse(pr([WATCHED]))
