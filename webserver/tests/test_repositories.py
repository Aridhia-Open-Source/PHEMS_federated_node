import json
import pytest
from app.models.repository import Repository


@pytest.fixture
def repository(client):
    repo = Repository(uri="github.com/org/repo")
    repo.add()
    return repo


@pytest.fixture
def repo_post_body():
    return {"uri": "github.com/org/another-repo"}


class TestGetRepositories:
    def test_list_empty(self, client, simple_admin_header):
        response = client.get("/repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_returns_repos(self, client, simple_admin_header, repository):
        response = client.get("/repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert len(response.json) == 1
        assert response.json[0]["uri"] == repository.uri

    def test_get_by_id(self, client, simple_admin_header, repository):
        response = client.get(f"/repositories/{repository.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json["id"] == repository.id
        assert response.json["uri"] == repository.uri
        assert response.json["pr_cursor"] == 0
        assert response.json["base_branch"] == "main"

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/repositories/9999", headers=simple_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client):
        response = client.get("/repositories/")
        assert response.status_code == 401


class TestPostRepository:
    def test_create(self, client, simple_admin_header, post_json_admin_header, repo_post_body):
        response = client.post(
            "/repositories/",
            data=json.dumps(repo_post_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json["uri"] == repo_post_body["uri"]
        assert response.json["base_branch"] == "main"
        assert response.json["pr_cursor"] == 0

    def test_create_with_custom_base_branch(self, client, post_json_admin_header):
        body = {"uri": "github.com/org/repo", "base_branch": "develop"}
        response = client.post("/repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["base_branch"] == "develop"

    def test_create_normalises_uri(self, client, post_json_admin_header):
        body = {"uri": "GitHub.com/Org/Repo/"}
        response = client.post("/repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/repo"

    def test_create_duplicate_uri_fails(self, client, post_json_admin_header, repository):
        body = {"uri": repository.uri}
        response = client.post("/repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_create_missing_uri_fails(self, client, post_json_admin_header):
        response = client.post("/repositories/", data=json.dumps({}), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_requires_auth(self, client):
        response = client.post("/repositories/", data=json.dumps({"uri": "x"}))
        assert response.status_code == 401


class TestPatchRepository:
    def test_update_pr_cursor(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/repositories/{repository.id}",
            data=json.dumps({"pr_cursor": 42}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["pr_cursor"] == 42

    def test_update_base_branch(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/repositories/{repository.id}",
            data=json.dumps({"base_branch": "develop"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["base_branch"] == "develop"

    def test_update_both_fields(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/repositories/{repository.id}",
            data=json.dumps({"pr_cursor": 10, "base_branch": "staging"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["pr_cursor"] == 10
        assert response.json["base_branch"] == "staging"

    def test_negative_pr_cursor_fails(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/repositories/{repository.id}",
            data=json.dumps({"pr_cursor": -1}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_empty_base_branch_fails(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/repositories/{repository.id}",
            data=json.dumps({"base_branch": ""}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_empty_body_fails(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/repositories/{repository.id}",
            data=json.dumps({}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_not_found(self, client, post_json_admin_header):
        response = client.patch(
            "/repositories/9999",
            data=json.dumps({"pr_cursor": 1}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_requires_auth(self, client, repository):
        response = client.patch(f"/repositories/{repository.id}", data=json.dumps({"pr_cursor": 1}))
        assert response.status_code == 401
