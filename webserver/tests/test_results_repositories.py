import pytest
from sqlalchemy.exc import IntegrityError

from app.dtos.results_repository import ResultsRepositoryDTO
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.project import Project
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository

# What a repository needs to say about its git host. The secret is the conftest secret.
REPO_FIELDS = {"provider": "github", "api_uri": "https://api.github.com", "secret_label": "test-creds"}


@pytest.fixture
def results_repo(client, project, secret):
    repo = ResultsRepository(
        uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
        secret_id=secret.id, target_dir="results", project_id=project.id
    )
    repo.add()
    return repo


@pytest.fixture
def results_post_body(project, secret):
    return {**REPO_FIELDS, "uri": "github.com/org/results", "target_dir": "results", "project_id": project.id}


def make_trigger(project, secret, uri="github.com/org/results", watch_dir="triggers"):
    repo = TriggerRepository(
        uri=uri, provider="github", api_uri="https://api.github.com",
        secret_id=secret.id, watch_dir=watch_dir, project_id=project.id
    )
    repo.add()
    return repo


class TestGetResultsRepositories:
    def test_list_empty(self, client, simple_admin_header):
        response = client.get("/results_repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_filtered_by_project(self, client, simple_admin_header, results_repo, other_project):
        response = client.get(f"/results_repositories?project_id={results_repo.project_id}", headers=simple_admin_header)
        assert [r["id"] for r in response.json] == [results_repo.id]
        response = client.get(f"/results_repositories?project_id={other_project.id}", headers=simple_admin_header)
        assert response.json == []

    def test_get_by_id(self, client, simple_admin_header, results_repo):
        response = client.get(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == ResultsRepositoryDTO.from_model(results_repo).dump()
        assert response.json["target_dir"] == "results"
        assert response.json["secret"]["label"] == "test-creds"
        assert response.json["owned_by_federated_node"] is True

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/results_repositories/9999", headers=simple_admin_header)
        assert response.status_code == 404


class TestPostResultsRepository:
    def test_create(self, client, post_json_admin_header, results_post_body):
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/results"
        assert response.json["target_dir"] == "results"
        assert ResultsRepository.query.count() == 1

    def test_create_normalises_uri(self, client, post_json_admin_header, results_post_body):
        body = {**results_post_body, "uri": "https://GitHub.com/org/results/"}
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/results"

    @pytest.mark.parametrize("field", ["uri", "project_id", "provider", "api_uri", "secret_label", "target_dir"])
    def test_create_requires_field(self, client, post_json_admin_header, results_post_body, field):
        del results_post_body[field]
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert field in response.json["error"]

    def test_second_repository_in_a_project_is_a_conflict(self, client, post_json_admin_header, results_repo, results_post_body):
        body = {**results_post_body, "uri": "github.com/org/another"}
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 409
        assert "already has a results repository" in response.json["error"]
        assert ResultsRepository.query.count() == 1

    def test_another_project_can_have_its_own(self, client, post_json_admin_header, results_repo, results_post_body, other_project):
        Secret(project_id=other_project.id, label="test-creds", provider=SecretProviderType.K8S).add()
        body = {**results_post_body, "project_id": other_project.id}
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201

    def test_create_with_another_projects_secret_fails(self, client, post_json_admin_header, results_post_body, other_project):
        Secret(project_id=other_project.id, label="foreign-creds", provider=SecretProviderType.K8S).add()
        body = {**results_post_body, "secret_label": "foreign-creds"}
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert ResultsRepository.query.count() == 0

    def test_create_with_unknown_project_fails(self, client, post_json_admin_header, results_post_body):
        response = client.post(
            "/results_repositories", json={**results_post_body, "project_id": 9999}, headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_create_with_unknown_provider_fails(self, client, post_json_admin_header, results_post_body):
        response = client.post(
            "/results_repositories", json={**results_post_body, "provider": "svn"}, headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_database_rejects_two_repositories_in_a_project(self, results_repo, secret):
        with pytest.raises(IntegrityError):
            ResultsRepository(
                uri="github.com/org/another", provider="github", api_uri="https://api.github.com",
                secret_id=secret.id, target_dir="results", project_id=results_repo.project_id
            ).add()


class TestPatchResultsRepository:
    def test_update_fields(self, client, post_json_admin_header, results_repo):
        body = {"target_dir": "out", "owned_by_federated_node": False, "api_uri": "https://git.example.com/api"}
        response = client.patch(f"/results_repositories/{results_repo.id}", json=body, headers=post_json_admin_header)
        assert response.status_code == 200
        assert response.json["target_dir"] == "out"
        assert response.json["owned_by_federated_node"] is False
        assert response.json["api_uri"] == "https://git.example.com/api"

    def test_empty_body(self, client, post_json_admin_header, results_repo):
        response = client.patch(f"/results_repositories/{results_repo.id}", json={}, headers=post_json_admin_header)
        assert response.status_code == 400

    def test_empty_target_dir(self, client, post_json_admin_header, results_repo):
        response = client.patch(f"/results_repositories/{results_repo.id}", json={"target_dir": ""}, headers=post_json_admin_header)
        assert response.status_code == 400

    def test_update_to_another_projects_secret_fails(self, client, post_json_admin_header, results_repo, other_project):
        Secret(project_id=other_project.id, label="foreign-creds", provider=SecretProviderType.K8S).add()
        response = client.patch(
            f"/results_repositories/{results_repo.id}", json={"secret_label": "foreign-creds"},
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_not_found(self, client, post_json_admin_header):
        response = client.patch("/results_repositories/9999", json={"target_dir": "x"}, headers=post_json_admin_header)
        assert response.status_code == 404


class TestDeleteResultsRepository:
    def test_delete(self, client, simple_admin_header, results_repo):
        response = client.delete(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert ResultsRepository.query.count() == 0

    def test_secret_in_use_cannot_be_deleted(self, client, simple_admin_header, results_repo, secret):
        response = client.delete(f"/projects/{secret.project_id}/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 409

    def test_project_reaches_its_repository_through_one_accessor(self, project, results_repo):
        assert Project.get_by_id(project.id).get_results_repository() == results_repo

    def test_project_without_repository(self, project):
        assert project.get_results_repository() is None


class TestLoopGuard:
    """A results repository and a trigger repository that are the same repository must not overlap."""

    def create_results(self, client, header, body, **changes):
        return client.post("/results_repositories", json={**body, **changes}, headers=header)

    def create_trigger(self, client, header, project, **changes):
        body = {**REPO_FIELDS, "uri": "github.com/org/results", "project_id": project.id, "watch_dir": "triggers", **changes}
        return client.post("/trigger_repositories", json=body, headers=header)

    @pytest.mark.parametrize("watch_dir,target_dir,ok", [
        ("triggers", "results", True),
        ("triggers", "triggers", False),
        ("triggers", "triggers/out", False),
        ("triggers/in", "triggers", False),
        ("triggers", "triggers-out", True),
        ("a/b", "a/c", True),
        ("/triggers/", "triggers", False),
        ("", "results", False),
    ])
    def test_results_created_after_trigger(self, client, post_json_admin_header, project, secret, results_post_body, watch_dir, target_dir, ok):
        make_trigger(project, secret, watch_dir=watch_dir)
        response = self.create_results(client, post_json_admin_header, results_post_body, target_dir=target_dir)
        assert (response.status_code == 201) is ok
        assert ResultsRepository.query.count() == (1 if ok else 0)

    @pytest.mark.parametrize("watch_dir,ok", [
        ("triggers", True),
        ("results", False),
        ("results/in", False),
        ("res", True),
        ("", False),
    ])
    def test_trigger_created_after_results(self, client, post_json_admin_header, project, results_repo, watch_dir, ok):
        response = self.create_trigger(client, post_json_admin_header, project, watch_dir=watch_dir)
        assert (response.status_code == 201) is ok
        assert TriggerRepository.query.count() == (1 if ok else 0)

    def test_trigger_without_watch_dir_is_refused_with_a_clear_message(self, client, post_json_admin_header, project, results_repo):
        body = {**REPO_FIELDS, "uri": "github.com/org/results", "project_id": project.id}
        response = client.post("/trigger_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "whole repository" in response.json["error"]

    def test_different_remotes_are_fine(self, client, post_json_admin_header, project, results_repo):
        response = self.create_trigger(client, post_json_admin_header, project, uri="github.com/org/elsewhere", watch_dir="results")
        assert response.status_code == 201

    def test_different_projects_are_fine(self, client, post_json_admin_header, project, results_repo, other_project):
        Secret(project_id=other_project.id, label="test-creds", provider=SecretProviderType.K8S).add()
        response = self.create_trigger(client, post_json_admin_header, other_project, watch_dir="results")
        assert response.status_code == 201

    def test_patching_watch_dir_into_the_results_dir_is_refused(self, client, post_json_admin_header, project, secret, results_repo):
        trigger = make_trigger(project, secret, watch_dir="triggers")
        response = client.patch(f"/trigger_repositories/{trigger.id}", json={"watch_dir": "results/x"}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert TriggerRepository.get_by_id(trigger.id).watch_dir == "triggers"

    def test_patching_target_dir_into_the_watch_dir_is_refused(self, client, post_json_admin_header, project, secret, results_repo):
        make_trigger(project, secret, watch_dir="triggers")
        response = client.patch(f"/results_repositories/{results_repo.id}", json={"target_dir": "triggers"}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert ResultsRepository.get_by_id(results_repo.id).target_dir == "results"

    def test_patching_to_a_clear_directory_is_fine(self, client, post_json_admin_header, project, secret, results_repo):
        make_trigger(project, secret, watch_dir="triggers")
        response = client.patch(f"/results_repositories/{results_repo.id}", json={"target_dir": "out"}, headers=post_json_admin_header)
        assert response.status_code == 200
