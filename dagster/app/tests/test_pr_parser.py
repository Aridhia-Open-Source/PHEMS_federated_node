import json
from unittest.mock import MagicMock

import pytest

from app.definitions.sensors.git.pr_parser import PullRequestParser
from app.models import PullRequest, PullRequestSpec, PullRequestStatus

WATCHED = {"filename": "specs/a.json", "status": "added"}


def pr():
    return PullRequest(
        trigger_repository_id=1, number=5, title="t", raised_by="dev",
        merged_at="2026-01-01T00:00:00Z", merge_commit_sha="abc", status="UNKNOWN", payload={},
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
def test_no_watched_file_is_ignored(files):
    assert parse(files)[0] == (PullRequestStatus.IGNORED, None)


def test_several_watched_files_are_invalid():
    files = [WATCHED, {"filename": "specs/b.json", "status": "added"}]

    assert parse(files)[0] == (PullRequestStatus.INVALID, None)


@pytest.mark.parametrize(
    "contents",
    ["not json", json.dumps({}), json.dumps({"spec": ["image"]}), json.dumps({"spec": {"env": {}}})],
)
def test_a_bad_spec_file_is_invalid(contents):
    assert parse([WATCHED], contents)[0] == (PullRequestStatus.INVALID, None)


def test_a_valid_spec_file_is_ready():
    (status, spec), git_api = parse([WATCHED], json.dumps({"spec": {"docker_image": "a/b:1"}}))

    assert status == PullRequestStatus.READY
    assert spec == PullRequestSpec(image="a/b:1")
    git_api.get_file_contents.assert_called_once_with(repo_path="org/repo", file_path="specs/a.json", ref="abc")
