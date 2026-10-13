import base64
from unittest.mock import MagicMock

import pytest

from app.gitea import GiteaAPI, GiteaClient


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def pr(number, merged_at, base="main"):
    return {"number": number, "merged_at": merged_at, "base": {"ref": base}}


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def api(client):
    return GiteaAPI(client=client, logger=MagicMock())


class TestGiteaClient:
    def test_sends_the_bearer_token_to_the_base_uri(self):
        session = MagicMock()

        client = GiteaClient(token="abc", session=session, base_uri="http://gitea:3000/api/v1/")

        session.headers.update.assert_called_with({"Authorization": "Bearer abc"})
        assert client._base_uri == "http://gitea:3000/api/v1"

    def test_defaults_to_the_in_cluster_gitea(self):
        assert GiteaClient(token="abc", session=MagicMock())._base_uri == "http://gitea.fn.svc:4000/api/v1"


class TestNewMergedPulls:
    def test_only_prs_merged_after_the_cursor_are_returned(self, api, client):
        client.request.side_effect = [response([
            pr(1, "2026-01-01T00:00:00Z"),
            pr(2, "2026-02-01T00:00:00Z"),
            pr(3, "2026-03-01T00:00:00Z"),
        ]), response([])]

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-15T00:00:00Z")

        assert [p["number"] for p in result] == [2, 3]

    def test_a_pr_merged_exactly_at_the_cursor_is_not_new(self, api, client):
        client.request.side_effect = [response([pr(1, "2026-01-01T00:00:00Z")]), response([])]

        assert api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z") == []

    def test_offsets_are_compared_as_instants(self, api, client):
        client.request.side_effect = [response([
            pr(1, "2026-01-01T10:00:00+02:00"),  # 08:00Z, before the cursor
            pr(2, "2026-01-01T10:00:00-02:00"),  # 12:00Z, after it
        ]), response([])]

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T09:00:00Z")

        assert [p["number"] for p in result] == [2]

    def test_closed_but_unmerged_prs_are_dropped(self, api, client):
        client.request.side_effect = [
            response([pr(1, None), {"number": 2, "base": {"ref": "main"}}, pr(3, "2026-03-01T00:00:00Z")]),
            response([]),
        ]

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert [p["number"] for p in result] == [3]

    def test_an_empty_cursor_returns_every_merged_pr(self, api, client):
        client.request.side_effect = [response([pr(1, "2020-01-01T00:00:00Z")]), response([])]

        assert len(api.get_new_merged_pulls("org/repo", "main", "")) == 1

    def test_the_closed_prs_are_requested_with_limit(self, api, client):
        client.request.return_value = response([])

        api.get_new_merged_pulls("org/repo", "dev", "2026-01-01T00:00:00Z")

        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["params"] == {"state": "closed", "limit": 50, "page": 1}

    def test_prs_of_other_base_branches_are_dropped(self, api, client):
        client.request.side_effect = [
            response([pr(1, "2026-02-01T00:00:00Z", base="dev"), pr(2, "2026-02-01T00:00:00Z")]),
            response([]),
        ]

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert [p["number"] for p in result] == [2]

    def test_pages_are_fetched_until_an_empty_one(self, api, client):
        short = [pr(1, "2026-02-01T00:00:00Z")]
        client.request.side_effect = [response(short), response([pr(2, "2026-02-01T00:00:00Z")]), response([])]

        result = api.get_new_merged_pulls("org/repo", "main", "2026-01-01T00:00:00Z")

        assert len(result) == 2
        assert client.request.call_count == 3
        assert client.request.call_args_list[1].kwargs["params"]["page"] == 2


class TestPullRequest:
    def test_get_pull_request(self, api, client):
        client.request.return_value = response({"number": 5})

        assert api.get_pull_request("org/repo", 5) == {"number": 5}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls/5")

    def test_files_paginate_until_an_empty_page(self, api, client):
        first = [{"filename": f"f{i}", "status": "added"} for i in range(50)]
        client.request.side_effect = [
            response(first), response([{"filename": "last", "status": "added"}]), response([]),
        ]

        files = api.get_pull_request_files("org/repo", 5)

        assert len(files) == 51
        assert client.request.call_args_list[1].kwargs["params"] == {"page": 2, "limit": 50}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls/5/files")

    def test_no_files(self, api, client):
        client.request.return_value = response([])

        assert api.get_pull_request_files("org/repo", 5) == []


class TestFileContents:
    def test_content_is_base64_decoded_at_the_ref(self, api, client):
        client.request.return_value = response({"content": base64.b64encode(b'{"a": 1}').decode()})

        assert api.get_file_contents("org/repo", "specs/a.json", "abc") == '{"a": 1}'
        assert client.request.call_args.args == ("GET", "repos/org/repo/contents/specs/a.json")
        assert client.request.call_args.kwargs["params"] == {"ref": "abc"}

    def test_a_response_without_content_is_empty(self, api, client):
        client.request.return_value = response({})

        assert api.get_file_contents("org/repo", "specs", "abc") == ""


class TestBranchPullRequests:
    def test_find_returns_the_pr(self, api, client):
        client.request.return_value = response({"number": 7})

        assert api.find_pull_request_by_branch("org/repo", "feature", "main") == {"number": 7}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls/main/feature")
        assert client.request.call_args.kwargs == {"raise_for_status": False}

    def test_find_returns_none_on_404(self, api, client):
        client.request.return_value = response({}, status_code=404)

        assert api.find_pull_request_by_branch("org/repo", "feature", "main") is None

    def test_find_raises_on_other_errors(self, api, client):
        resp = response({}, status_code=500)
        resp.raise_for_status.side_effect = RuntimeError("500")
        client.request.return_value = resp

        with pytest.raises(RuntimeError):
            api.find_pull_request_by_branch("org/repo", "feature", "main")

    def test_create_posts_head_and_base(self, api, client):
        client.request.return_value = response({"number": 8})

        assert api.create_pull_request("org/repo", "feature", "main", "T", "B") == {"number": 8}
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["json"] == {
            "title": "T", "body": "B", "head": "feature", "base": "main",
        }
