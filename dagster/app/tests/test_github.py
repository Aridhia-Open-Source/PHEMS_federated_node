import base64
from unittest.mock import MagicMock

import pytest

from app.github import GithubAPI, GithubClient


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def merged_pr(number, merged_at, updated_at=None):
    return {"number": number, "merged_at": merged_at, "updated_at": updated_at or merged_at or "2026-01-01T00:00:00Z"}


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def api(client):
    return GithubAPI(client=client, logger=MagicMock())


class TestGithubClient:
    def test_sends_the_github_accept_header(self):
        session = MagicMock()

        GithubClient(token="abc", session=session)

        session.headers.update.assert_any_call({"Accept": "application/vnd.github+json"})

    def test_defaults_to_the_public_api(self):
        client = GithubClient(token="abc", session=MagicMock())

        assert client._base_uri == "https://api.github.com"

    def test_base_uri_is_overridable(self):
        client = GithubClient(
            token="abc", session=MagicMock(), base_uri="https://github.example.com/api/v3"
        )

        assert client._base_uri == "https://github.example.com/api/v3"


class TestPullRequests:
    def test_get_pull_request(self, api, client):
        client.request.return_value = response({"number": 5})

        assert api.get_pull_request("org/repo", 5) == {"number": 5}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls/5")

    def test_closed_prs_of_the_base_branch_are_listed_newest_update_first(self, api, client):
        client.request.return_value = response([])

        api.get_new_merged_pulls("org/repo", "dev", "2026-01-01T00:00:00Z")

        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["params"] == {
            "state": "closed", "base": "dev", "sort": "updated", "direction": "desc",
            "per_page": 100, "page": 1,
        }

    def test_only_prs_merged_after_the_cursor_are_returned(self, api, client):
        client.request.return_value = response([
            merged_pr(3, "2026-03-01T00:00:00Z"),
            merged_pr(2, "2026-02-01T00:00:00Z"),
            # updated after the cursor, merged before it
            merged_pr(1, "2026-01-01T00:00:00Z", updated_at="2026-04-01T00:00:00Z"),
        ])

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-15T00:00:00Z")

        assert [p["number"] for p in result] == [3, 2]

    def test_a_pr_merged_exactly_at_the_cursor_is_not_new(self, api, client):
        client.request.return_value = response([
            merged_pr(1, "2026-01-01T00:00:00Z", updated_at="2026-02-01T00:00:00Z"),
        ])

        assert api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z") == []

    def test_closed_but_unmerged_prs_are_dropped(self, api, client):
        client.request.return_value = response([
            merged_pr(2, None, updated_at="2026-03-01T00:00:00Z"),
            merged_pr(1, "2026-02-01T00:00:00Z"),
        ])

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert [p["number"] for p in result] == [1]

    def test_a_pr_updated_before_the_cursor_ends_the_listing(self, api, client):
        full = [merged_pr(i, "2026-02-01T00:00:00Z") for i in range(99)]
        full.append(merged_pr(99, "2025-12-01T00:00:00Z"))
        client.request.return_value = response(full)

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert len(result) == 99
        assert client.request.call_count == 1

    def test_a_full_page_fetches_the_next_one(self, api, client):
        full = [merged_pr(i, "2026-02-01T00:00:00Z") for i in range(100)]
        client.request.side_effect = [response(full), response([merged_pr(200, "2026-02-01T00:00:00Z")])]

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert len(result) == 101
        assert client.request.call_count == 2
        assert client.request.call_args_list[1].kwargs["params"]["page"] == 2


class TestPullRequestFiles:
    def test_files_paginate_until_empty(self, api, client):
        client.request.side_effect = [
            response([{"filename": "a.json"}]),
            response([{"filename": "b.json"}]),
            response([]),
        ]

        files = api.get_pull_request_files("org/repo", 5)

        assert [f["filename"] for f in files] == ["a.json", "b.json"]


class TestContents:
    def test_file_contents_are_base64_decoded(self, api, client):
        content = base64.b64encode(b'{"spec": {}}').decode()
        client.request.return_value = response({"content": content})

        assert api.get_file_contents("org/repo", "specs/new.json", "abc123") == '{"spec": {}}'
        assert client.request.call_args.kwargs["params"] == {"ref": "abc123"}


class TestWrites:
    def test_create_pull_request_returns_the_pr(self, api, client):
        client.request.return_value = response({"html_url": "https://github.com/org/repo/pull/6"})

        pr = api.create_pull_request(
            "org/repo", head_branch="results/pr-5", base_branch="main", title="t", body="b"
        )

        assert pr["html_url"] == "https://github.com/org/repo/pull/6"
        assert client.request.call_args.kwargs["json"] == {
            "title": "t", "body": "b", "head": "results/pr-5", "base": "main",
        }


class TestBranchPullRequests:
    def test_find_returns_the_first_pr_of_the_branch(self, api, client):
        client.request.return_value = response([{"number": 7}, {"number": 3}])

        assert api.find_pull_request_by_branch("org/repo", "feature", "main") == {"number": 7}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["params"] == {
            "head": "org:feature", "base": "main", "state": "all",
        }

    def test_find_returns_none_without_one(self, api, client):
        client.request.return_value = response([])

        assert api.find_pull_request_by_branch("org/repo", "feature", "main") is None
