from unittest.mock import MagicMock

import pytest

from app.gitea import GiteaAPI
from app.github import GithubAPI


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def github(client):
    return GithubAPI(client=client, logger=MagicMock())


@pytest.fixture
def gitea(client):
    return GiteaAPI(client=client, logger=MagicMock())


@pytest.mark.parametrize("api", ["github", "gitea"])
def test_the_default_branch_is_the_repository_s(api, request, client):
    client.request.return_value = response({"default_branch": "main", "name": "repo"})

    assert request.getfixturevalue(api).get_default_branch("org/repo") == "main"
    assert client.request.call_args.args == ("GET", "repos/org/repo")


class TestGithubFindPullRequestByBranch:
    def test_returns_the_matching_pr(self, github, client):
        client.request.return_value = response([{"number": 7, "state": "open"}])

        pr = github.find_pull_request_by_branch("org/repo", "results/task-1", "main")

        assert pr == {"number": 7, "state": "open"}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["params"] == {
            "head": "org:results/task-1", "base": "main", "state": "all"
        }

    def test_returns_none_when_there_is_no_pr(self, github, client):
        client.request.return_value = response([])

        assert github.find_pull_request_by_branch("org/repo", "results/task-1", "main") is None

    def test_returns_a_closed_pr(self, github, client):
        client.request.return_value = response([{"number": 3, "state": "closed"}])

        pr = github.find_pull_request_by_branch("org/repo", "results/task-1", "main")

        assert pr["state"] == "closed"


class TestGithubCreatePullRequest:
    def test_posts_the_pr_and_returns_it(self, github, client):
        client.request.return_value = response({"number": 9, "html_url": "https://github.com/org/repo/pull/9"})

        pr = github.create_pull_request("org/repo", "results/task-1", "main", "Title", "Body")

        assert pr["html_url"] == "https://github.com/org/repo/pull/9"
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["json"] == {
            "title": "Title", "body": "Body", "head": "results/task-1", "base": "main"
        }


class TestGiteaFindPullRequestByBranch:
    def test_returns_the_matching_pr(self, gitea, client):
        client.request.return_value = response({"number": 4, "state": "open"})

        pr = gitea.find_pull_request_by_branch("org/repo", "results/task-1", "main")

        assert pr == {"number": 4, "state": "open"}
        assert client.request.call_args.args == ("GET", "repos/org/repo/pulls/main/results/task-1")

    def test_returns_none_on_404(self, gitea, client):
        client.request.return_value = response({}, status_code=404)

        assert gitea.find_pull_request_by_branch("org/repo", "results/task-1", "main") is None

    def test_returns_a_closed_pr(self, gitea, client):
        client.request.return_value = response({"number": 4, "state": "closed"})

        pr = gitea.find_pull_request_by_branch("org/repo", "results/task-1", "main")

        assert pr["state"] == "closed"

    def test_other_errors_are_raised(self, gitea, client):
        resp = response({}, status_code=500)
        resp.raise_for_status.side_effect = RuntimeError("boom")
        client.request.return_value = resp

        with pytest.raises(RuntimeError):
            gitea.find_pull_request_by_branch("org/repo", "results/task-1", "main")


class TestGiteaCreatePullRequest:
    def test_posts_the_pr_and_returns_it(self, gitea, client):
        client.request.return_value = response({"number": 2, "html_url": "http://gitea/org/repo/pulls/2"})

        pr = gitea.create_pull_request("org/repo", "results/task-1", "main", "Title", "Body")

        assert pr["number"] == 2
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["json"] == {
            "title": "Title", "body": "Body", "head": "results/task-1", "base": "main"
        }
