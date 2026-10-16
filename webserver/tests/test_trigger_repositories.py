"""Global trigger repositories, /trigger_repositories. A project's assignment of one is in test_project_trigger_repositories.py."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.dtos.trigger_repository import TriggerRepositoryDTO
from app.helpers.base_model import db
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.trigger_repository import TriggerRepository

# What a repository needs to say about its git host. The secret is the conftest secret.
REPO_FIELDS = {"provider": "github", "api_uri": "https://api.github.com", "secret_label": "test-creds"}


@pytest.fixture
def repo_post_body(secret):
    return {**REPO_FIELDS, "uri": "github.com/org/another-repo"}


class TestGetRepositories:
    def test_list_empty(self, client, simple_admin_header):
        response = client.get("/trigger_repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_is_global(self, client, simple_admin_header, trigger_repo, default_repo):
        response = client.get("/trigger_repositories", headers=simple_admin_header)
        assert [r["id"] for r in response.json] == [trigger_repo.id]
        assert set(response.json[0]) == {"id", "uri", "provider", "api_uri", "secret"}

    def test_list_includes_an_unassigned_repository(self, client, simple_admin_header, trigger_repo):
        response = client.get("/trigger_repositories", headers=simple_admin_header)
        assert [r["uri"] for r in response.json] == [trigger_repo.uri]

    def test_get_by_id(self, client, simple_admin_header, trigger_repo):
        response = client.get(f"/trigger_repositories/{trigger_repo.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == TriggerRepositoryDTO.from_model(trigger_repo).dump()
        assert response.json["secret"]["label"] == "test-creds"

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/trigger_repositories/9999", headers=simple_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client):
        response = client.get("/trigger_repositories/")
        assert response.status_code == 401


class TestPostRepository:
    def test_create(self, client, post_json_admin_header, repo_post_body):
        response = client.post("/trigger_repositories/", json=repo_post_body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == repo_post_body["uri"]
        assert set(response.json) == {"id", "uri", "provider", "api_uri", "secret"}
        assert TriggerRepository.query.count() == 1
        assert ProjectTriggerRepository.query.count() == 0

    def test_only_an_admin_writes(self, client, post_json_user_header, repo_post_body, trigger_repo, mock_kc_client):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.side_effect = (
            lambda token, scope, *args, **kwargs: scope != 'can_do_admin'
        )
        url = f"/trigger_repositories/{trigger_repo.id}"
        assert client.post("/trigger_repositories", json=repo_post_body, headers=post_json_user_header).status_code == 403
        assert client.patch(url, json={"provider": "gitea"}, headers=post_json_user_header).status_code == 403
        assert client.delete(url, headers=post_json_user_header).status_code == 403
        assert TriggerRepository.query.count() == 1

    @pytest.mark.parametrize("field", ["project_id", "watch_dir", "base_branch", "initial_cursor"])
    def test_create_rejects_assignment_fields(self, client, post_json_admin_header, repo_post_body, field):
        response = client.post(
            "/trigger_repositories", json={**repo_post_body, field: 1}, headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert TriggerRepository.query.count() == 0

    def test_create_defaults_the_api_uri(self, client, post_json_admin_header, repo_post_body):
        del repo_post_body["api_uri"]
        response = client.post("/trigger_repositories/", json=repo_post_body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["api_uri"] == "https://api.github.com"

    def test_create_defaults_the_gitea_api_uri_to_the_repository_host(self, client, post_json_admin_header, repo_post_body):
        body = {**repo_post_body, "provider": "gitea", "uri": "gitea.fn.svc:4000/org/repo"}
        del body["api_uri"]
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["api_uri"] == "https://gitea.fn.svc:4000/api/v1"

    def test_create_normalises_uri(self, client, post_json_admin_header, repo_post_body):
        body = {**repo_post_body, "uri": "GitHub.com/Org/Repo/"}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/repo"

    @pytest.mark.parametrize("uri", ["github.com/org", "ssh://github.com/org/repo", "https://u:p@github.com/org/repo"])
    def test_create_rejects_an_unparsable_uri(self, client, post_json_admin_header, repo_post_body, uri):
        response = client.post("/trigger_repositories/", json={**repo_post_body, "uri": uri}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "Invalid repository uri" in response.json["error"]

    @pytest.mark.parametrize("api_uri", [
        "ftp://api.github.com", "https://user:pass@api.github.com", "https://evil.example.com/api", "https://github.com"
    ])
    def test_create_rejects_an_api_uri_not_on_the_repository_host(self, client, post_json_admin_header, repo_post_body, api_uri):
        response = client.post("/trigger_repositories/", json={**repo_post_body, "api_uri": api_uri}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "api_uri" in response.json["error"]

    def test_create_accepts_a_gitea_api_uri_on_the_repository_host(self, client, post_json_admin_header, repo_post_body):
        body = {**repo_post_body, "provider": "gitea", "uri": "http://gitea.fn.svc:4000/org/repo", "api_uri": "http://gitea.fn.svc:4000/api/v1"}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["api_uri"] == "http://gitea.fn.svc:4000/api/v1"

    def test_create_strips_the_git_suffix(self, client, post_json_admin_header, repo_post_body):
        body = {**repo_post_body, "uri": "https://github.com/Org/Repo.git"}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/repo"

    def test_the_same_uri_twice_is_a_conflict(self, client, post_json_admin_header, trigger_repo):
        body = {**REPO_FIELDS, "uri": trigger_repo.uri}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 409
        assert TriggerRepository.query.count() == 1

    def test_the_same_uri_in_another_form_is_a_conflict(self, client, post_json_admin_header, trigger_repo):
        body = {**REPO_FIELDS, "uri": "https://GitHub.com/Org/Test-Repo/"}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 409

    def test_create_normalises_the_uri_and_derives_repo_path(self, client, post_json_admin_header, repo_post_body):
        body = {**repo_post_body, "uri": "https://GitHub.com/Org/Another-Repo/"}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/another-repo"
        assert "repo_path" not in response.json
        assert TriggerRepository.get_by_id(response.json["id"]).repo_path == "org/another-repo"

    def test_repo_path_is_the_last_two_segments_of_a_sub_path_uri(self, client, post_json_admin_header, repo_post_body):
        body = {**repo_post_body, "uri": "host/gitea/owner/repo", "api_uri": "https://host/gitea/api/v1"}
        response = client.post("/trigger_repositories/", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "host/gitea/owner/repo"
        assert TriggerRepository.get_by_id(response.json["id"]).repo_path == "owner/repo"

    def test_database_rejects_duplicate_uri(self, trigger_repo, secret):
        duplicate = TriggerRepository(
            uri=trigger_repo.uri, provider="github", api_uri="https://api.github.com", secret_id=secret.id
        )
        with pytest.raises(IntegrityError):
            duplicate.add()
        db.session.rollback()

    def test_create_missing_uri_fails(self, client, post_json_admin_header, repo_post_body):
        del repo_post_body["uri"]
        response = client.post("/trigger_repositories/", json=repo_post_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "uri is required" in response.json["error"]

    def test_create_returns_the_git_host_and_secret(self, client, post_json_admin_header, repo_post_body):
        response = client.post("/trigger_repositories/", json=repo_post_body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["provider"] == "github"
        assert response.json["api_uri"] == "https://api.github.com"
        assert response.json["secret"]["label"] == "test-creds"
        assert response.json["secret"]["key"] == "fn-secret-test-creds"
        assert "secret_label" not in response.json

    @pytest.mark.parametrize("field", ["provider", "secret_label"])
    def test_create_requires_the_git_host_and_secret(self, client, post_json_admin_header, repo_post_body, field):
        del repo_post_body[field]
        response = client.post("/trigger_repositories/", json=repo_post_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert f"{field} is required" in response.json["error"]

    def test_create_rejects_an_unknown_provider(self, client, post_json_admin_header, repo_post_body):
        repo_post_body["provider"] = "gitlab"
        response = client.post("/trigger_repositories/", json=repo_post_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "provider must be one of" in response.json["error"]

    def test_create_with_unknown_secret_fails(self, client, post_json_admin_header, repo_post_body):
        response = client.post(
            "/trigger_repositories", json={**repo_post_body, "secret_label": "nope"}, headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_requires_auth(self, client):
        response = client.post("/trigger_repositories/", json={"uri": "x"})
        assert response.status_code == 401


class TestPatchRepository:
    def patch(self, client, headers, repository, body):
        return client.patch(f"/trigger_repositories/{repository.id}", json=body, headers=headers)

    def test_update_provider_and_api_uri(self, client, post_json_admin_header, trigger_repo):
        response = self.patch(
            client, post_json_admin_header, trigger_repo,
            {"provider": "gitea", "api_uri": "https://api.github.com/api/v3"}
        )
        assert response.status_code == 200
        assert response.json["provider"] == "gitea"
        assert response.json["api_uri"] == "https://api.github.com/api/v3"

    @pytest.mark.parametrize("api_uri", [
        "ftp://api.github.com", "https://user:pass@api.github.com", "https://evil.example.com/api", "https://github.com"
    ])
    def test_update_rejects_an_api_uri_not_on_the_repository_host(self, client, post_json_admin_header, trigger_repo, api_uri):
        response = self.patch(client, post_json_admin_header, trigger_repo, {"api_uri": api_uri})
        assert response.status_code == 400
        assert "api_uri" in response.json["error"]
        assert trigger_repo.api_uri == "https://api.github.com"

    def test_update_rejects_an_unknown_provider(self, client, post_json_admin_header, trigger_repo):
        response = self.patch(client, post_json_admin_header, trigger_repo, {"provider": "gitlab"})
        assert response.status_code == 400
        assert trigger_repo.provider == "github"

    def test_update_to_another_secret(self, client, post_json_admin_header, trigger_repo):
        Secret(label="other-creds", provider=SecretProviderType.K8S).add()
        response = self.patch(client, post_json_admin_header, trigger_repo, {"secret_label": "other-creds"})
        assert response.status_code == 200
        assert response.json["secret"]["label"] == "other-creds"

    def test_update_to_a_missing_secret_fails(self, client, post_json_admin_header, trigger_repo):
        response = self.patch(client, post_json_admin_header, trigger_repo, {"secret_label": "missing"})
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]
        assert trigger_repo.secret.label == "test-creds"

    @pytest.mark.parametrize("field", ["provider", "api_uri", "secret_label"])
    def test_git_host_fields_cannot_be_emptied(self, client, post_json_admin_header, trigger_repo, field):
        response = self.patch(client, post_json_admin_header, trigger_repo, {field: ""})
        assert response.status_code == 400
        assert f"{field} cannot be empty" in response.json["error"]

    @pytest.mark.parametrize("field", ["watch_dir", "base_branch", "initial_cursor", "project_id", "uri"])
    def test_assignment_fields_and_uri_are_not_updatable(self, client, post_json_admin_header, trigger_repo, field):
        response = self.patch(client, post_json_admin_header, trigger_repo, {field: "x"})
        assert response.status_code == 400

    def test_empty_body_fails(self, client, post_json_admin_header, trigger_repo):
        assert self.patch(client, post_json_admin_header, trigger_repo, {}).status_code == 400

    def test_not_found(self, client, post_json_admin_header):
        response = client.patch("/trigger_repositories/9999", json={"provider": "gitea"}, headers=post_json_admin_header)
        assert response.status_code == 404

    def test_unassigned_repository_needs_no_lock(self, client, post_json_admin_header, trigger_repo):
        assert self.patch(client, post_json_admin_header, trigger_repo, {"provider": "gitea"}).status_code == 200

    def test_edit_needs_every_assigned_project_drained(
        self, client, post_json_admin_header, trigger_repo, default_repo, project, other_project
    ):
        ProjectTriggerRepository(other_project.id, trigger_repo.id, watch_dir="other").add()
        project.locked = True
        other_project.locked = False
        db.session.commit()
        response = self.patch(client, post_json_admin_header, trigger_repo, {"provider": "gitea"})
        assert response.status_code == 409
        assert TriggerRepository.get_by_id(trigger_repo.id).provider == "github"

        other_project.locked = True
        db.session.commit()
        assert self.patch(client, post_json_admin_header, trigger_repo, {"provider": "gitea"}).status_code == 200

    def test_secret_rotation_alone_is_exempt(
        self, client, post_json_admin_header, trigger_repo, default_repo, project, make_task, secret
    ):
        make_task(project=project, status="RUNNING")
        response = self.patch(client, post_json_admin_header, trigger_repo, {"secret_label": secret.label})
        assert response.status_code == 200

    def test_requires_auth(self, client, trigger_repo):
        assert client.patch(f"/trigger_repositories/{trigger_repo.id}", json={"provider": "gitea"}).status_code == 401


class TestDeleteRepository:
    def test_delete_unassigned(self, client, simple_admin_header, trigger_repo):
        response = client.delete(f"/trigger_repositories/{trigger_repo.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert TriggerRepository.query.count() == 0

    def test_delete_removes_the_assignments(self, client, simple_admin_header, trigger_repo, default_repo, lock_project):
        response = client.delete(f"/trigger_repositories/{trigger_repo.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert TriggerRepository.query.count() == 0
        assert ProjectTriggerRepository.query.count() == 0

    def test_delete_needs_the_assigned_projects_locked(self, client, simple_admin_header, trigger_repo, default_repo):
        response = client.delete(f"/trigger_repositories/{trigger_repo.id}", headers=simple_admin_header)
        assert response.status_code == 409
        assert TriggerRepository.query.count() == 1

    def test_delete_is_refused_while_pull_requests_exist(
        self, client, simple_admin_header, trigger_repo, default_repo, lock_project
    ):
        PullRequestTrigger(
            lock_project.id, default_repo.id, 1, "t", "user", "2026-01-01T10:00:00Z", "a" * 40
        ).add()
        response = client.delete(f"/trigger_repositories/{trigger_repo.id}", headers=simple_admin_header)
        assert response.status_code == 400
        assert (TriggerRepository.query.count(), ProjectTriggerRepository.query.count()) == (1, 1)

    def test_delete_not_found(self, client, simple_admin_header):
        assert client.delete("/trigger_repositories/9999", headers=simple_admin_header).status_code == 404

    def test_secret_in_use_cannot_be_deleted(self, client, simple_admin_header, trigger_repo, secret):
        response = client.delete(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 409


class TestTriggerRepositoryDTO:
    def test_fields(self, trigger_repo):
        sanitized = TriggerRepositoryDTO.from_model(trigger_repo).dump()
        assert set(sanitized) == {"id", "uri", "provider", "api_uri", "secret"}
