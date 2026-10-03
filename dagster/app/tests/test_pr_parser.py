import json
from unittest.mock import MagicMock

import pytest

from app.definitions.sensors.git.pr_parser import PullRequestOutcome, PullRequestParser
from app.models import PullRequest, PullRequestSpec

WATCHED = {"filename": "specs/a.json", "status": "added"}


def pr():
    return PullRequest(
        trigger_repository_id=1, number=5, title="t", raised_by="dev",
        merged_at="2026-01-01T00:00:00Z", merge_commit_sha="abc", state="UNKNOWN", payload={},
    )


def parse(files, contents=None):
    git_api = MagicMock()
    git_api.get_pull_request_files.return_value = files
    git_api.get_file_contents.return_value = contents
    repo = MagicMock(path="org/repo", watch_dir="specs/")
    return PullRequestParser(git_api, repo, MagicMock()).parse(pr()), git_api


@pytest.mark.parametrize(
    "files",
    [
        [],
        [{"filename": "docs/a.json", "status": "added"}],
        [{"filename": "specs/a.txt", "status": "added"}],
        [{"filename": "specs/a.json", "status": "modified"}],
    ],
)
def test_no_watched_file_is_ignored_with_a_reason(files):
    parsed = parse(files)[0]

    assert parsed.outcome == PullRequestOutcome.IGNORED
    assert parsed.spec is None
    assert "specs/" in parsed.reason


def test_several_watched_files_are_rejected_naming_them():
    files = [WATCHED, {"filename": "specs/b.json", "status": "added"}]

    parsed = parse(files)[0]

    assert parsed.outcome == PullRequestOutcome.REJECTED
    assert "specs/a.json" in parsed.reason and "specs/b.json" in parsed.reason


@pytest.mark.parametrize(
    "contents",
    ["not json", json.dumps({}), json.dumps({"spec": ["image"]}), json.dumps({"spec": {"env": {}}})],
)
def test_a_bad_spec_file_is_rejected_with_a_reason(contents):
    parsed = parse([WATCHED], contents)[0]

    assert parsed.outcome == PullRequestOutcome.REJECTED
    assert parsed.spec is None
    assert "specs/a.json" in parsed.reason


def test_a_valid_spec_file_is_ready():
    parsed, git_api = parse([WATCHED], json.dumps({"spec": {"docker_image": "a/b:1"}}))

    assert parsed.outcome == PullRequestOutcome.READY
    assert parsed.reason is None
    assert parsed.spec == PullRequestSpec(image="a/b:1")
    git_api.get_file_contents.assert_called_once_with(repo_path="org/repo", file_path="specs/a.json", ref="abc")


def test_a_git_failure_raises_instead_of_rejecting():
    git_api = MagicMock()
    git_api.get_pull_request_files.return_value = [WATCHED]
    git_api.get_file_contents.side_effect = ConnectionError("git down")
    repo = MagicMock(path="org/repo", watch_dir="specs/")

    with pytest.raises(ConnectionError):
        PullRequestParser(git_api, repo, MagicMock()).parse(pr())
