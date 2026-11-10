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


class TestGithubCreatePullRequest:
    def test_posts_the_pr_and_returns_it(self, github, client):
        client.request.return_value = response({"number": 9, "html_url": "https://github.com/org/repo/pull/9"})

        pr = github.create_pull_request("org/repo", "results/task-1", "main", "Title", "Body")

        assert pr["html_url"] == "https://github.com/org/repo/pull/9"
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["json"] == {
            "title": "Title", "body": "Body", "head": "results/task-1", "base": "main"
        }


class TestGiteaCreatePullRequest:
    def test_posts_the_pr_and_returns_it(self, gitea, client):
        client.request.return_value = response({"number": 2, "html_url": "http://gitea/org/repo/pulls/2"})

        pr = gitea.create_pull_request("org/repo", "results/task-1", "main", "Title", "Body")

        assert pr["number"] == 2
        assert client.request.call_args.args == ("POST", "repos/org/repo/pulls")
        assert client.request.call_args.kwargs["json"] == {
            "title": "Title", "body": "Body", "head": "results/task-1", "base": "main"
        }
