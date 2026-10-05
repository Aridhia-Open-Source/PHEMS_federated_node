import pytest
import requests
from http import HTTPStatus
from datetime import datetime, timezone
from unittest.mock import ANY, Mock

from kubernetes.client.exceptions import ApiException

from app.helpers.base_model import db
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository


class TestGetProjects:
    def test_list_projects(self, client, project, simple_admin_header):
        response = client.get("/projects", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert any(item["id"] == project.id for item in response.json["items"])

    def test_get_project_by_id(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert response.json["name"] == project.name

    def test_get_project_not_found(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id + 100}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.skip(reason="This test is not working as expected, needs to be fixed")
    def test_requires_auth(self, client, project, simple_user_header, mock_kc_client):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        response = client.get("/projects", headers=simple_user_header)
        assert response.status_code == HTTPStatus.FORBIDDEN


class TestPostProject:
    def test_create_project(self, client, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": "newproject"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED, response.json
        assert Project.query.filter_by(name="newproject").one_or_none() is not None

    def test_create_project_with_description(self, client, post_json_admin_header):
        response = client.post(
            "/projects",
            json={"name": "described", "description": "what it is for"},
            headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED
        assert Project.query.filter_by(name="described").one().description == "what it is for"

    def test_create_duplicate_name_fails(self, client, project, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": project.name}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CONFLICT

    def test_create_without_name_fails(self, client, post_json_admin_header):
        response = client.post("/projects", json={}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_new_project_has_no_default_dataset(self, client, post_json_admin_header):
        """
        A project starts with no default. The first dataset created in it becomes one.
        """
        response = client.post(
            "/projects", json={"name": "empty"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED
        assert Project.query.filter_by(name="empty").one().default_dataset_id is None


    def test_new_project_is_disabled_by_default(self, client, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": "off"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED
        assert Project.query.filter_by(name="off").one().enabled is False

    def test_create_enabled_project(self, client, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": "on", "enabled": True}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED
        assert Project.query.filter_by(name="on").one().enabled is True

    def test_create_with_non_boolean_enabled_fails(self, client, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": "bad", "enabled": "yes"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert Project.query.filter_by(name="bad").one_or_none() is None


class TestPatchProject:
    def test_enable_project(self, client, project, post_json_admin_header):
        assert project.enabled is False
        response = client.patch(
            f"/projects/{project.id}", json={"enabled": True}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json["enabled"] is True
        assert Project.query.filter_by(id=project.id).one().enabled is True

    def test_disable_project(self, client, project, post_json_admin_header):
        client.patch(
            f"/projects/{project.id}", json={"enabled": True}, headers=post_json_admin_header
        )
        response = client.patch(
            f"/projects/{project.id}", json={"enabled": False}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json["enabled"] is False

    def test_get_project_shows_enabled(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id}", headers=simple_admin_header)
        assert response.json["enabled"] is False

    def test_patch_with_non_boolean_fails(self, client, project, post_json_admin_header):
        response = client.patch(
            f"/projects/{project.id}", json={"enabled": "yes"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_without_enabled_fails(self, client, project, post_json_admin_header):
        response = client.patch(
            f"/projects/{project.id}", json={"name": "renamed"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_project_not_found(self, client, project, post_json_admin_header):
        response = client.patch(
            f"/projects/{project.id + 100}", json={"enabled": True}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


class TestProjectDefaultDataset:
    """
    The seed creates a project, creates a dataset in it, and on a re-run deletes the
    dataset and creates another. The default has to survive that.
    """

    def test_first_dataset_becomes_the_default(self, client, project, dataset):
        assert project.default_dataset_id == dataset.id

    def test_second_dataset_does_not_displace_it(
            self, client, project, dataset, user_uuid, k8s_client, mock_kc_client
        ):
        from app.models.dataset import Dataset
        second = Dataset(
            name="SecondDs", host="example.com", secret_id=dataset.secret_id,
            project_id=project.id
        )
        second.add(user_id=user_uuid)
        assert project.default_dataset_id == dataset.id

    def test_deleting_the_default_clears_it(self, client, project, dataset):
        """
        SET NULL rather than blocking, so re-seeding can drop the dataset and add another.
        """
        dataset.delete()
        assert project.default_dataset_id is None

    def test_reseeding_sets_a_new_default(
            self, client, project, dataset, secret, user_uuid, k8s_client, mock_kc_client
        ):
        from app.models.dataset import Dataset
        dataset.delete()
        replacement = Dataset(
            name="Reseeded", host="example.com", secret_id=secret.id,
            project_id=project.id
        )
        replacement.add(user_id=user_uuid)
        assert project.default_dataset_id == replacement.id


class TestModelRegistry:
    def test_every_relationship_resolves(self, client):
        """
        Project names WhitelistedImage by string. Nothing imports
        whitelisted_image for its own sake, so if create_app() stops registering it the
        mapper cannot resolve the name and every ORM query raises. The app was shipped
        broken this way once because only the test harness imported it.
        """
        from sqlalchemy.orm import configure_mappers
        configure_mappers()

    def test_project_relationships_are_queryable(self, client, project):
        assert project.whitelisted_images == []
        assert project.datasets == []
        assert project.results_backend is None
        assert project.triggers == []


class TestProjectHealthcheck:
    URL = "https://api.github.com/repos/org/test-repo"

    @pytest.fixture
    def git_api(self, mocker):
        return mocker.patch(
            "app.models.git_repository.requests.get",
            return_value=Mock(status_code=200, ok=True, reason="OK"),
        )

    def get(self, client, project, header):
        return client.get(f"/projects/{project.id}/healthcheck", headers=header)

    def test_reports_project_and_repository(self, client, project, default_repo, git_api, simple_admin_header):
        response = self.get(client, project, simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert response.json["id"] == project.id
        assert response.json["name"] == project.name
        assert response.json["status"] == "ok"
        [repo] = response.json["trigger_repositories"]
        assert repo["id"] == default_repo.id
        assert repo["uri"] == default_repo.uri
        assert repo["provider"] == "github"
        assert repo["status"] == "ok"
        assert repo["health_check"]["message"] == "OK"
        assert repo["health_check"]["status_code"] == 200
        assert isinstance(repo["health_check"]["latency_ms"], int)
        assert repo["health_check"]["latency_ms"] >= 0
        assert "detail" not in repo

    def test_checks_the_api_uri_with_the_bearer_token(self, client, project, default_repo, git_api, simple_admin_header):
        self.get(client, project, simple_admin_header)
        git_api.assert_called_once_with(
            self.URL, headers={"Authorization": "Bearer abc123"}, timeout=5
        )

    def test_checks_the_repo_path_derived_from_a_sub_path_uri(
        self, client, k8s_client, project, secret, git_api, simple_admin_header
    ):
        TriggerRepository(
            uri="host/gitea/owner/repo", provider="gitea", api_uri="https://host/gitea/api/v1",
            secret_id=secret.id, watch_dir="", project_id=project.id
        ).add()
        self.get(client, project, simple_admin_header)
        git_api.assert_called_once_with(
            "https://host/gitea/api/v1/repos/owner/repo",
            headers={"Authorization": "Bearer abc123"}, timeout=5,
        )

    def test_response_never_contains_the_token(self, client, project, default_repo, git_api, simple_admin_header):
        response = self.get(client, project, simple_admin_header)
        assert "abc123" not in response.get_data(as_text=True)

    @pytest.mark.parametrize("code, status", [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (404, "not_found"),
        (503, "error"),
    ])
    def test_provider_rejections(self, client, project, default_repo, git_api, simple_admin_header, code, status):
        git_api.return_value = Mock(status_code=code, ok=False, reason="Rejected")
        response = self.get(client, project, simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert response.json["status"] == "error"
        [repo] = response.json["trigger_repositories"]
        assert repo["status"] == status
        assert repo["health_check"]["status_code"] == code
        assert repo["health_check"]["message"] == "Rejected"

    def test_message_is_the_providers_own(self, client, project, default_repo, git_api, simple_admin_header):
        git_api.return_value = Mock(
            status_code=401, ok=False, reason="Unauthorized",
            json=Mock(return_value={"message": "Bad credentials"}),
        )
        response = self.get(client, project, simple_admin_header)
        [repo] = response.json["trigger_repositories"]
        assert repo["health_check"]["message"] == "Bad credentials"

    def test_message_falls_back_to_the_reason_when_the_body_is_not_json(self, client, project, default_repo, git_api, simple_admin_header):
        git_api.return_value = Mock(
            status_code=502, ok=False, reason="Bad Gateway", json=Mock(side_effect=ValueError),
        )
        response = self.get(client, project, simple_admin_header)
        [repo] = response.json["trigger_repositories"]
        assert repo["health_check"]["message"] == "Bad Gateway"

    def test_long_provider_messages_are_truncated(self, client, project, default_repo, git_api, simple_admin_header):
        git_api.return_value = Mock(
            status_code=500, ok=False, reason="Server Error",
            json=Mock(return_value={"message": "x" * 1000}),
        )
        response = self.get(client, project, simple_admin_header)
        [repo] = response.json["trigger_repositories"]
        assert len(repo["health_check"]["message"]) == 200

    def test_unreachable_provider(self, client, project, default_repo, git_api, simple_admin_header):
        git_api.side_effect = requests.ConnectionError("connection refused")
        response = self.get(client, project, simple_admin_header)
        [repo] = response.json["trigger_repositories"]
        assert repo["status"] == "unreachable"
        assert repo["health_check"]["message"] == "ConnectionError"
        assert repo["health_check"]["status_code"] is None
        assert isinstance(repo["health_check"]["latency_ms"], int)

    def test_secret_missing_from_the_cluster(self, client, project, default_repo, git_api, k8s_client, simple_admin_header):
        k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)
        response = self.get(client, project, simple_admin_header)
        [repo] = response.json["trigger_repositories"]
        assert repo["status"] == "secret_missing"
        assert "not found" in repo["health_check"]["message"]
        assert repo["health_check"]["status_code"] is None
        assert repo["health_check"]["latency_ms"] is None
        git_api.assert_not_called()

    def test_secret_without_a_token(self, client, project, default_repo, git_api, k8s_client, simple_admin_header):
        k8s_client["read_namespaced_secret_mock"].return_value.data = {}
        response = self.get(client, project, simple_admin_header)
        [repo] = response.json["trigger_repositories"]
        assert repo["status"] == "secret_missing"

    def test_one_bad_repository_makes_the_project_unhealthy(self, client, project, default_repo, secret, git_api, simple_admin_header):
        TriggerRepository(
            uri="github.com/org/other", provider="github", api_uri="https://api.github.com",
            secret_id=secret.id, watch_dir="", project_id=project.id,
        ).add()
        git_api.side_effect = [
            Mock(status_code=200, ok=True, reason="OK"),
            Mock(status_code=404, ok=False, reason="Not Found"),
        ]
        response = self.get(client, project, simple_admin_header)
        assert response.json["status"] == "error"
        assert sorted(r["status"] for r in response.json["trigger_repositories"]) == ["not_found", "ok"]

    def test_project_without_repositories(self, client, project, git_api, simple_admin_header):
        response = self.get(client, project, simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert response.json["trigger_repositories"] == []
        assert response.json["status"] == "error"
        git_api.assert_not_called()

    def test_reports_pull_request_count_per_repository(self, client, project, default_repo, secret, git_api, simple_admin_header):
        other = TriggerRepository(
            uri="github.com/org/other", provider="github", api_uri="https://api.github.com",
            secret_id=secret.id, watch_dir="", project_id=project.id,
        )
        other.add()
        merged_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for repo, numbers in ((default_repo, (1, 2, 3)), (other, (1,))):
            for number in numbers:
                PullRequest(project.id, repo.id, number, f"PR {number}", "user", merged_at, f"sha{number}").add()
        response = self.get(client, project, simple_admin_header)
        counts = {r["id"]: r["pr_count"] for r in response.json["trigger_repositories"]}
        assert counts == {default_repo.id: 3, other.id: 1}

    def test_pull_request_count_is_zero_without_pull_requests(self, client, project, default_repo, git_api, simple_admin_header):
        response = self.get(client, project, simple_admin_header)
        assert response.json["trigger_repositories"][0]["pr_count"] == 0

    def test_reports_the_results_repository(self, client, project, secret, git_api, k8s_client, simple_admin_header):
        results = ResultsRepository(
            uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
            secret_id=secret.id, target_dir="results", project_id=project.id,
            owned_by_federated_node=False,
        )
        results.add()
        response = self.get(client, project, simple_admin_header)
        assert response.json["results_repository"] == {
            "id": results.id, "uri": "github.com/org/results", "owned_by_federated_node": False,
            "target_dir": "results", "status": "ok",
            "health_check": {"message": "OK", "status_code": 200, "latency_ms": ANY},
        }

    def test_bad_results_repository_makes_the_project_unhealthy(self, client, project, default_repo, secret, git_api, simple_admin_header):
        ResultsRepository(
            uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
            secret_id=secret.id, target_dir="results", project_id=project.id,
        ).add()
        git_api.side_effect = [
            Mock(status_code=200, ok=True, reason="OK"),
            Mock(status_code=404, ok=False, reason="Not Found"),
        ]
        response = self.get(client, project, simple_admin_header)
        assert response.json["status"] == "error"
        assert response.json["trigger_repositories"][0]["status"] == "ok"
        assert response.json["results_repository"]["status"] == "not_found"

    def test_good_results_repository_keeps_the_project_healthy(self, client, project, default_repo, secret, git_api, simple_admin_header):
        ResultsRepository(
            uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
            secret_id=secret.id, target_dir="results", project_id=project.id,
        ).add()
        response = self.get(client, project, simple_admin_header)
        assert response.json["status"] == "ok"

    def test_no_results_repository_does_not_make_the_project_unhealthy(self, client, project, default_repo, git_api, simple_admin_header):
        response = self.get(client, project, simple_admin_header)
        assert response.json["status"] == "ok"

    def test_no_results_repository(self, client, project, git_api, simple_admin_header):
        response = self.get(client, project, simple_admin_header)
        assert response.json["results_repository"] is None

    def test_project_not_found(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id + 100}/healthcheck", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.NOT_FOUND


class TestDeleteProject:
    @pytest.fixture
    def full_project(self, client, k8s_client, project, dataset, default_repo, secret, make_task, results_repo_for):
        make_task(project=project, dataset_id=dataset.id)
        return project

    @pytest.fixture
    def results_repo_for(self, client, project, secret):
        repo = ResultsRepository(
            uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
            secret_id=secret.id, target_dir="results", project_id=project.id
        )
        repo.add()
        return repo

    def delete(self, client, headers, project):
        return client.delete(f"/projects/{project.id}", headers=headers)

    def test_deletes_everything_under_the_project(
        self, client, k8s_client, simple_admin_header, full_project, secret
    ):
        from app.models.dataset import Dataset
        from app.models.secret import Secret
        from app.models.task import Task
        from app.models.trigger import Trigger
        key, namespace = secret.key, secret.namespace
        project_id = full_project.id

        response = self.delete(client, simple_admin_header, full_project)

        assert response.status_code == HTTPStatus.NO_CONTENT
        assert Project.query.filter_by(id=project_id).count() == 0
        for model in (Task, Dataset, TriggerRepository, ResultsRepository, Secret):
            assert model.query.filter_by(project_id=project_id).count() == 0
        assert Trigger.query.filter_by(project_id=project_id).count() == 0
        k8s_client["delete_namespaced_secret_mock"].assert_called_once_with(key, namespace)

    def test_other_projects_are_untouched(self, client, k8s_client, simple_admin_header, full_project, other_project):
        self.delete(client, simple_admin_header, full_project)
        assert Project.query.filter_by(id=other_project.id).count() == 1

    def test_not_found(self, client, simple_admin_header):
        assert client.delete("/projects/9999", headers=simple_admin_header).status_code == 404

    def test_requires_auth(self, client, project):
        assert client.delete(f"/projects/{project.id}").status_code == 401

    def test_a_missing_cluster_secret_is_fine(self, client, k8s_client, simple_admin_header, full_project):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=404)
        assert self.delete(client, simple_admin_header, full_project).status_code == HTTPStatus.NO_CONTENT

    def test_deletes_a_project_with_pull_requests(
        self, client, k8s_client, simple_admin_header, full_project, default_repo
    ):
        PullRequest(
            project_id=full_project.id, trigger_repository_id=default_repo.id, number=1, title="t",
            raised_by="u", merged_at="2026-01-01T10:00:00Z", merge_commit_sha="a" * 40
        ).add()
        assert self.delete(client, simple_admin_header, full_project).status_code == HTTPStatus.NO_CONTENT
        assert PullRequest.query.count() == 0
