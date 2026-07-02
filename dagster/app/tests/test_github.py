import base64
import json
import pytest
from unittest.mock import Mock

from app.github import GithubClient, GithubRepo
from app.tests.conftest import make_response


@pytest.fixture
def client():
    return GithubClient(token="test-token", session=Mock())


@pytest.fixture
def repo(client):
    return GithubRepo(client=client, uri="github.com/org/repo", base_branch="main")


def encode_content(data: dict) -> str:
    return base64.b64encode(json.dumps(data).encode()).decode()


# ---------------------------------------------------------------------------
# GithubClient
# ---------------------------------------------------------------------------

class TestGithubClient:
    def test_sets_auth_header(self):
        session = Mock()
        session.headers = {}
        GithubClient(token="mytoken", session=session)
        assert session.headers["Authorization"] == "Bearer mytoken"

    def test_request_prepends_base_url(self):
        session = Mock()
        session.headers = {}
        session.request.return_value = Mock(status_code=200, raise_for_status=Mock())
        api = GithubClient(token="t", session=session)
        api.request("GET", "/repos/org/repo/pulls")
        call_url = session.request.call_args[0][1]
        assert call_url == "https://api.github.com/repos/org/repo/pulls"

    def test_strips_leading_slash_from_path(self):
        session = Mock()
        session.headers = {}
        session.request.return_value = Mock(status_code=200, raise_for_status=Mock())
        api = GithubClient(token="t", session=session)
        api.request("GET", "search/issues")
        call_url = session.request.call_args[0][1]
        assert call_url == "https://api.github.com/search/issues"


# ---------------------------------------------------------------------------
# GithubRepo — _repo_uri parsing
# ---------------------------------------------------------------------------

class TestGithubRepo:
    def test_repo_uri_strips_domain(self, client):
        repo = GithubRepo(client=client, uri="github.com/myorg/myrepo", base_branch="main")
        assert repo._repo_uri == "myorg/myrepo"

    def test_default_base_branch(self, client):
        repo = GithubRepo(client=client, uri="github.com/org/repo")
        assert repo.base_branch == "main"


# ---------------------------------------------------------------------------
# GithubAPI — get_new_merged_pulls
# ---------------------------------------------------------------------------

class TestGetNewMergedPulls:
    def test_returns_empty_when_no_items(self, repo, mocker):
        mocker.patch.object(repo.client, "request", return_value=make_response({"items": []}))
        result = repo.get_new_merged_pulls(cursor="2026-01-01T00:00:00Z", watch_dir="requests/")
        assert result == []

    def test_returns_prs_with_watched_files(self, repo, mocker):
        search = make_response({"items": [{"number": 3}]})
        pr = make_response({"number": 3, "merged_at": "2026-06-01T00:00:00Z", "merge_commit_sha": "abc"})
        files = make_response([{"filename": "requests/spec.json", "status": "added"}])

        mocker.patch.object(repo.client, "request", side_effect=[
            search,
            pr,
            files,
            make_response([]),
            make_response({"items": []}),
        ])

        result = repo.get_new_merged_pulls(cursor="2026-01-01T00:00:00Z", watch_dir="requests/")
        assert len(result) == 1
        assert result[0]["number"] == 3
        assert result[0]["watched_files"] == ["requests/spec.json"]

    def test_skips_prs_without_watched_files(self, repo, mocker):
        search = make_response({"items": [{"number": 3}]})
        pr = make_response({"number": 3, "merged_at": "2026-06-01T00:00:00Z", "merge_commit_sha": "abc"})
        files = make_response([{"filename": "src/code.py", "status": "added"}])

        mocker.patch.object(repo.client, "request", side_effect=[
            search, pr,
            files, make_response([]),
            make_response({"items": []}),
        ])

        result = repo.get_new_merged_pulls(cursor="2026-01-01T00:00:00Z", watch_dir="requests/")
        assert result == []


# ---------------------------------------------------------------------------
# GithubAPI — get_merged_prs_after_number
# ---------------------------------------------------------------------------

class TestGetMergedPrsAfterNumber:
    def test_returns_empty_when_no_items(self, repo, mocker):
        mocker.patch.object(repo.client, "request", return_value=make_response({"items": []}))
        result = repo.get_merged_prs_after_number(pr_cursor=10, watch_dir="requests/")
        assert result == []

    def test_returns_prs_with_number_greater_than_cursor(self, repo, mocker):
        search = make_response({"items": [{"number": 11}, {"number": 12}]})
        pr_11 = make_response({"number": 11, "merged_at": "2026-06-01T00:00:00Z", "merge_commit_sha": "abc"})
        pr_12 = make_response({"number": 12, "merged_at": "2026-06-02T00:00:00Z", "merge_commit_sha": "def"})
        files = make_response([{"filename": "requests/spec.json", "status": "added"}])

        mocker.patch.object(repo.client, "request", side_effect=[
            search,
            pr_11, files, make_response([]),
            pr_12, files, make_response([]),
            make_response({"items": []}),
        ])

        result = repo.get_merged_prs_after_number(pr_cursor=10, watch_dir="requests/")
        assert len(result) == 2
        assert {pr["number"] for pr in result} == {11, 12}

    def test_excludes_prs_at_or_below_cursor(self, repo, mocker):
        search = make_response({"items": [{"number": 10}, {"number": 9}]})
        mocker.patch.object(repo.client, "request", return_value=search)

        result = repo.get_merged_prs_after_number(pr_cursor=10, watch_dir="requests/")
        assert result == []

    def test_stops_paginating_when_page_contains_only_old_prs(self, repo, mocker):
        page1 = make_response({"items": [{"number": 15}, {"number": 12}]})
        pr_15 = make_response({"number": 15, "merged_at": "2026-06-05T00:00:00Z", "merge_commit_sha": "aaa"})
        pr_12 = make_response({"number": 12, "merged_at": "2026-06-02T00:00:00Z", "merge_commit_sha": "bbb"})
        files = make_response([{"filename": "requests/spec.json", "status": "added"}])
        page2 = make_response({"items": [{"number": 9}]})

        request_mock = mocker.patch.object(repo.client, "request", side_effect=[
            page1,
            pr_15, files, make_response([]),
            pr_12, files, make_response([]),
            page2,
        ])

        result = repo.get_merged_prs_after_number(pr_cursor=10, watch_dir="requests/")
        assert len(result) == 2
        assert request_mock.call_count == 8


# ---------------------------------------------------------------------------
# GithubAPI — get_file_contents
# ---------------------------------------------------------------------------

class TestGetFileContents:
    def test_decodes_base64_content(self, repo, mocker):
        data = {"spec": {"docker_image": "img:latest"}}
        encoded = encode_content(data)
        mocker.patch.object(
            repo.client, "request",
            return_value=make_response({"content": encoded + "\n"})
        )
        result = repo.get_file_contents("requests/spec.json", ref="abc123")
        assert json.loads(result) == data


# ---------------------------------------------------------------------------
# GithubAPI — get_pull_request_files
# ---------------------------------------------------------------------------

class TestGetPullRequestFiles:
    def test_paginates_until_empty(self, repo, mocker):
        page1 = make_response([{"filename": "a.py", "status": "added"}])
        page2 = make_response([{"filename": "b.py", "status": "modified"}])
        page3 = make_response([])

        mocker.patch.object(repo.client, "request", side_effect=[page1, page2, page3])

        result = repo.get_pull_request_files(pr_number=1)
        assert len(result) == 2

    def test_returns_empty_on_no_files(self, repo, mocker):
        mocker.patch.object(repo.client, "request", return_value=make_response([]))
        result = repo.get_pull_request_files(pr_number=1)
        assert result == []


# ---------------------------------------------------------------------------
# GithubAPI — _filter_watched_dir
# ---------------------------------------------------------------------------

class TestFilterWatchedDir:
    def test_matches_added_json_in_watch_dir(self, repo):
        files = [
            {"filename": "requests/spec.json", "status": "added"},
            {"filename": "requests/other.txt", "status": "added"},
            {"filename": "src/code.py", "status": "added"},
            {"filename": "requests/spec.json", "status": "modified"},
        ]
        assert repo._filter_watched_dir(files, "requests/") == ["requests/spec.json"]

    def test_returns_empty_when_no_matches(self, repo):
        files = [{"filename": "src/code.py", "status": "added"}]
        assert repo._filter_watched_dir(files, "requests/") == []
