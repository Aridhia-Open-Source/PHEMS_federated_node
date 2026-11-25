from unittest.mock import MagicMock

import pytest
import requests

from fednode.clients.git.gitea import GiteaClient
from fednode.clients.git.github import GH_API_BASE_URL, GitHubClient


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
    api = GitHubClient(GH_API_BASE_URL, "abc", session=MagicMock())
    api.request = client.request
    return api


@pytest.fixture
def gitea(client):
    api = GiteaClient("http://gitea:3000/api/v1", "abc", session=MagicMock())
    api.request = client.request
    return api


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


class TestBranchesAndFiles:
    def test_github_makes_a_branch_with_a_ref_at_the_sha_of_the_old_one(self, github, client):
        client.request.side_effect = [response({"object": {"sha": "abc123"}}), response({})]

        github.create_branch("org/repo", "feature", "main")

        assert client.request.call_args_list[0].args == ("GET", "repos/org/repo/git/ref/heads/main")
        assert client.request.call_args_list[1].args == ("POST", "repos/org/repo/git/refs")
        assert client.request.call_args_list[1].kwargs["json"] == {"ref": "refs/heads/feature", "sha": "abc123"}

    def test_gitea_makes_a_branch_from_the_old_one_by_name(self, gitea, client):
        client.request.return_value = response({})

        gitea.create_branch("org/repo", "feature", "main")

        assert client.request.call_args.args == ("POST", "repos/org/repo/branches")
        assert client.request.call_args.kwargs["json"] == {"new_branch_name": "feature", "old_branch_name": "main"}

    def test_github_commits_a_new_file_with_a_put(self, github, client):
        client.request.return_value = response({})

        github.create_file("org/repo", "specs/a.json", "{}", message="Add a", branch="feature")

        assert client.request.call_args.args == ("PUT", "repos/org/repo/contents/specs/a.json")
        assert client.request.call_args.kwargs["json"] == {"content": "e30=", "message": "Add a", "branch": "feature"}

    def test_gitea_commits_a_new_file_with_a_post(self, gitea, client):
        client.request.return_value = response({})

        gitea.create_file("org/repo", "specs/a.json", "{}", message="Add a", branch="feature")

        assert client.request.call_args.args == ("POST", "repos/org/repo/contents/specs/a.json")
        assert client.request.call_args.kwargs["json"] == {"content": "e30=", "message": "Add a", "branch": "feature"}


class TestMerge:
    def test_github_merges_with_a_merge_commit(self, github, client):
        client.request.return_value = response({})

        github.merge_pull_request("org/repo", 3)

        assert client.request.call_args.args == ("PUT", "repos/org/repo/pulls/3/merge")
        assert client.request.call_args.kwargs["json"] == {"merge_method": "merge"}

    def test_github_retries_while_it_computes_mergeability(self, github, client, monkeypatch):
        monkeypatch.setattr("fednode.clients.git.provider.time.sleep", lambda seconds: None)
        client.request.side_effect = [requests.HTTPError(response=MagicMock(status_code=405)), response({})]

        github.merge_pull_request("org/repo", 3)

        assert client.request.call_count == 2
