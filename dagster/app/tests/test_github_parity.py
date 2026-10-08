"""Results delivery helpers against GitHub-shaped repositories and responses."""

import base64

import pytest

from app.delivery import git_push
from app.models import MergeStatus


@pytest.mark.parametrize("uri, api_uri, expected", [
    ("github.com/org/results", "https://api.github.com", "https://github.com/org/results.git"),
    ("ghe.example.com/org/results", "https://ghe.example.com/api/v3", "https://ghe.example.com/org/results.git"),
])
def test_clone_url_is_on_the_repository_host_not_the_api_host(uri, api_uri, expected):
    assert git_push.clone_url(uri, api_uri) == expected


def test_the_token_is_sent_as_github_x_access_token_basic_auth():
    header = git_push.auth_env("tok")["GIT_CONFIG_VALUE_0"]

    assert base64.b64decode(header.removeprefix("Authorization: Basic ")).decode() == "x-access-token:tok"


@pytest.mark.parametrize("pr, expected", [
    # GitHub fills merge_commit_sha on an open PR with its test merge
    ({"state": "open", "merged": False, "merged_at": None, "merge_commit_sha": "abc"}, MergeStatus.OPEN),
    ({"state": "closed", "merged": True, "merged_at": "2026-10-08T12:00:00Z", "merge_commit_sha": "def"},
     MergeStatus.MERGED),
    ({"state": "closed", "merged": False, "merged_at": None, "merge_commit_sha": "abc"}, MergeStatus.CLOSED),
])
def test_github_merge_statuss(pr, expected):
    assert MergeStatus.from_git(pr) == expected
