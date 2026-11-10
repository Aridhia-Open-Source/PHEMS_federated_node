import base64
from unittest.mock import MagicMock

import pytest
import requests

from app.gitea import GiteaAPI, GiteaClient


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def pr(number, merged_at, base="main", updated_at=None):
    return {
        "number": number, "merged_at": merged_at, "updated_at": updated_at or merged_at, "base": {"ref": base},
    }


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


class TestPulls:
    def test_only_prs_merged_after_the_cursor_are_returned(self, api, client):
        client.request.side_effect = [response([
            pr(3, "2026-03-01T00:00:00Z"),
            pr(2, "2026-02-01T00:00:00Z"),
            # updated after the cursor, merged before it
            pr(1, "2026-01-01T00:00:00Z", updated_at="2026-04-01T00:00:00Z"),
        ]), response([])]

        result = api.get_pulls("org/repo", "2026-01-15T00:00:00Z", state="closed", merged_only=True)

        assert [p["number"] for p in result] == [3, 2]

    def test_a_pr_merged_exactly_at_the_cursor_is_not_new(self, api, client):
        client.request.side_effect = [
            response([pr(1, "2026-01-01T00:00:00Z", updated_at="2026-02-01T00:00:00Z")]), response([]),
        ]

        assert api.get_pulls("org/repo", "2026-01-01T00:00:00Z", state="closed", merged_only=True) == []

    def test_offsets_are_compared_as_instants(self, api, client):
        client.request.side_effect = [response([
            pr(2, "2026-01-01T10:00:00-02:00"),  # 12:00Z, after the cursor
            pr(1, "2026-01-01T10:00:00+02:00"),  # 08:00Z, before it
        ]), response([])]

        result = api.get_pulls("org/repo", "2026-01-01T09:00:00Z", state="closed", merged_only=True)

        assert [p["number"] for p in result] == [2]

    def test_closed_but_unmerged_prs_are_dropped_when_only_merged_are_wanted(self, api, client):
        client.request.side_effect = [
            response([pr(3, "2026-03-01T00:00:00Z"), pr(2, None, updated_at="2026-02-01T00:00:00Z")]),
            response([]),
        ]

        result = api.get_pulls("org/repo", "2026-01-01T00:00:00Z", state="closed", merged_only=True)

        assert [p["number"] for p in result] == [3]

    def test_every_pr_updated_after_since_is_returned_without_merged_only(self, api, client):
        client.request.side_effect = [response([
            pr(3, None, updated_at="2026-03-01T00:00:00Z"),  # open
            pr(2, "2026-02-01T00:00:00Z"),
            pr(1, None, updated_at="2026-01-10T00:00:00Z"),  # closed unmerged, updated before since
        ])]

        result = api.get_pulls("org/repo", "2026-01-15T00:00:00Z")

        assert [p["number"] for p in result] == [3, 2]
        assert client.request.call_count == 1

    def test_a_pr_updated_before_since_ends_the_listing(self, api, client):
        client.request.side_effect = [response([
            pr(2, "2026-02-01T00:00:00Z"),
            pr(1, None, updated_at="2025-12-01T00:00:00Z"),
        ])]

        result = api.get_pulls("org/repo", "2026-01-01T00:00:00Z")

        assert [p["number"] for p in result] == [2]
        assert client.request.call_count == 1

    def test_the_prs_are_requested_newest_update_first_with_limit(self, api, client):
        client.request.return_value = response([])

        api.get_pulls("org/repo", "2026-01-01T00:00:00Z", state="closed", merged_only=True)

        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["params"] == {
            "state": "closed", "sort": "recentupdate", "limit": 50, "page": 1,
        }

    def test_the_state_defaults_to_all(self, api, client):
        client.request.return_value = response([])

        api.get_pulls("org/repo", "2026-01-01T00:00:00Z")

        assert client.request.call_args.kwargs["params"]["state"] == "all"

    def test_prs_of_every_base_branch_are_returned(self, api, client):
        client.request.side_effect = [
            response([pr(1, "2026-02-01T00:00:00Z", base="dev"), pr(2, "2026-02-01T00:00:00Z")]),
            response([]),
        ]

        result = api.get_pulls("org/repo", "2026-01-01T00:00:00Z", state="closed", merged_only=True)

        assert [p["number"] for p in result] == [1, 2]

    def test_pages_are_fetched_until_an_empty_one(self, api, client):
        short = [pr(1, "2026-02-01T00:00:00Z")]
        client.request.side_effect = [response(short), response([pr(2, "2026-02-01T00:00:00Z")]), response([])]

        result = api.get_pulls("org/repo", "2026-01-01T00:00:00Z", state="closed", merged_only=True)

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


class TestCreatePullRequest:
    def test_create_posts_head_and_base(self, api, client):
        client.request.return_value = response({"number": 8})

        assert api.create_pull_request("org/repo", "feature", "main", "T", "B") == {"number": 8}
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["json"] == {
            "title": "T", "body": "B", "head": "feature", "base": "main",
        }


class TestMergePullRequest:
    def test_retries_while_gitea_computes_mergeability(self, api, client, monkeypatch):
        monkeypatch.setattr("app.gitea.time.sleep", lambda seconds: None)
        busy = requests.HTTPError(response=MagicMock(status_code=405))
        client.request.side_effect = [busy, response({})]

        api.merge_pull_request("org/repo", 3)

        assert client.request.call_count == 2
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls/3/merge")
        assert client.request.call_args.kwargs["json"] == {"Do": "merge"}

    def test_raises_any_other_error_at_once(self, api, client):
        client.request.side_effect = requests.HTTPError(response=MagicMock(status_code=409))

        with pytest.raises(requests.HTTPError):
            api.merge_pull_request("org/repo", 3)

        assert client.request.call_count == 1
