import base64
from unittest.mock import MagicMock

import pytest

from app.github import GithubAPI, GithubClient


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


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

    def test_merged_pulls_are_searched_by_branch_and_date(self, api, client):
        client.request.side_effect = [response({"items": [{"number": 5}]}), response({"items": []})]

        results = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert [pr["number"] for pr in results] == [5]
        query = client.request.call_args_list[0].kwargs["params"]["q"]
        assert "repo:org/repo" in query
        assert "is:pr is:merged" in query
        assert "base:main" in query
        assert "merged:>2026-01-01T00:00:00Z" in query

    def test_merged_pulls_paginate_until_empty(self, api, client):
        client.request.side_effect = [
            response({"items": [{"number": 5}]}),
            response({"items": [{"number": 6}]}),
            response({"items": []}),
        ]

        results = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert [pr["number"] for pr in results] == [5, 6]
        assert client.request.call_args_list[-1].kwargs["params"]["page"] == 3


class TestPullRequestFiles:
    def test_files_paginate_until_empty(self, api, client):
        client.request.side_effect = [
            response([{"filename": "a.json"}]),
            response([{"filename": "b.json"}]),
            response([]),
        ]

        files = api.get_pull_request_files("org/repo", 5)

        assert [f["filename"] for f in files] == ["a.json", "b.json"]

    def test_watched_files_must_be_added_in_the_watch_dir(self, api):
        files = [
            {"filename": "specs/new.json", "status": "added"},
            {"filename": "specs/changed.json", "status": "modified"},
            {"filename": "other/new.json", "status": "added"},
            {"filename": "specs/new.txt", "status": "added"},
        ]

        watched = api._filter_watched_dir(files, "specs/", ".json")

        assert watched == ["specs/new.json"]

    def test_any_extension_is_watched_by_default(self, api):
        files = [{"filename": "specs/new.txt", "status": "added"}]

        assert api._filter_watched_dir(files, "specs/") == ["specs/new.txt"]

    def test_prs_without_watched_files_are_dropped(self, api, client):
        prs = [{"number": 5, "base": {"repo": {"full_name": "org/repo"}}}]
        client.request.side_effect = [
            response({"number": 5}),
            response([{"filename": "docs/readme.md", "status": "added"}]),
            response([]),
        ]

        assert api.filter_prs_by_watch_dir(prs, "specs/", ".json") == []

    def test_prs_with_watched_files_are_annotated(self, api, client):
        prs = [{"number": 5, "base": {"repo": {"full_name": "org/repo"}}}]
        client.request.side_effect = [
            response({"number": 5}),
            response([{"filename": "specs/new.json", "status": "added"}]),
            response([]),
        ]

        results = api.filter_prs_by_watch_dir(prs, "specs/", ".json")

        assert results[0]["watched_files"] == ["specs/new.json"]


class TestContents:
    def test_file_contents_are_base64_decoded(self, api, client):
        content = base64.b64encode(b'{"spec": {}}').decode()
        client.request.return_value = response({"content": content})

        assert api.get_file_contents("org/repo", "specs/new.json", "abc123") == '{"spec": {}}'
        assert client.request.call_args.kwargs["params"] == {"ref": "abc123"}


class TestWrites:
    def test_comments_post_a_body(self, api, client):
        client.request.return_value = response({"id": 1})

        api.add_pull_request_comment("org/repo", 5, "done")

        assert client.request.call_args.args == (
            "POST", "repos/org/repo/issues/5/comments",
        )
        assert client.request.call_args.kwargs["json"] == {"body": "done"}

    def test_branch_exists(self, api, client):
        client.request.return_value = response({}, status_code=200)

        assert api.branch_exists("org/repo", "results/pr-5") is True

    def test_missing_branch_does_not_raise(self, api, client):
        client.request.return_value = response({}, status_code=404)

        assert api.branch_exists("org/repo", "results/pr-5") is False
        assert client.request.call_args.kwargs["raise_for_status"] is False

    def test_create_pull_request_returns_the_url(self, api, client):
        client.request.return_value = response({"html_url": "https://github.com/org/repo/pull/6"})

        url = api.create_pull_request(
            "org/repo", head="results/pr-5", base="main", title="t", body="b"
        )

        assert url == "https://github.com/org/repo/pull/6"
        assert client.request.call_args.kwargs["json"] == {
            "title": "t", "body": "b", "head": "results/pr-5", "base": "main",
        }
