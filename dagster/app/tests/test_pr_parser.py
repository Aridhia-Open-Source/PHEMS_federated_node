import json
from unittest.mock import MagicMock

import pytest

from app.definitions.sensors.git.pr_parser import PullRequestOutcome, PullRequestParser, is_under_dir
from app.models import PullRequestTrigger

WATCHED = {"filename": "specs/a.json", "status": "added"}


def pr():
    return PullRequestTrigger(
        project_id=1, trigger_repository_id=1, number=5, title="t", raised_by="dev",
        merged_at="2026-01-01T00:00:00Z", merge_commit_sha="abc", state="UNKNOWN",
    )


def parse(files, contents=None):
    git_api = MagicMock()
    git_api.get_pull_request_files.return_value = files
    git_api.get_file_contents.return_value = contents
    repo = MagicMock(repo_path="org/repo", watch_dir="specs/")
    return PullRequestParser(git_api, repo, MagicMock()).parse(pr()), git_api


@pytest.mark.parametrize(
    "files",
    [
        [],
        [{"filename": "docs/a.json", "status": "added"}],
        [{"filename": "specs/a.txt", "status": "added"}],
        [{"filename": "specs/a.json", "status": "modified"}],
        [{"filename": "specs-old/a.json", "status": "added"}],
    ],
)
def test_no_watched_file_is_rejected_with_a_reason(files):
    parsed = parse(files)[0]

    assert parsed.outcome == PullRequestOutcome.REJECTED
    assert parsed.spec_raw is None
    assert "specs/" in parsed.state_cause


def test_several_watched_files_are_rejected_naming_them():
    files = [WATCHED, {"filename": "specs/b.json", "status": "added"}]

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
    git_api.get_pull_request_files.return_value = [WATCHED]
    git_api.get_file_contents.side_effect = ConnectionError("git down")
    repo = MagicMock(repo_path="org/repo", watch_dir="specs/")

    with pytest.raises(ConnectionError):
        PullRequestParser(git_api, repo, MagicMock()).parse(pr())


@pytest.mark.parametrize(
    "watch_dir,filename,expected",
    [
        ("data", "data/x.json", True),
        ("data", "database/x.json", False),
        ("data/", "data/x.json", True),
        ("./data", "data/x.json", True),
        ("dagster/triggers", "dagster/triggers-results/x.json", False),
        ("dagster/triggers", "dagster/triggers/x.json", True),
        ("dagster/triggers", "dagster/triggers/sub/x.json", True),
        ("dagster/triggers", "dagster/x.json", False),
        ("", "x.json", True),
        ("", "a/b/x.json", True),
    ],
)
def test_files_are_watched_by_path_segment(watch_dir, filename, expected):
    assert is_under_dir(filename, watch_dir) is expected
