import json
import pytest
from app.dtos.trigger_repository import TriggerRepositoryDTO
from app.models.pull_request import PullRequest
from app.models.trigger_repository import TriggerRepository
from app.models.dataset import Dataset
from app.models.k8s_secret import K8sSecret

# What a repository needs to say about its git host. The secret is the conftest k8s_secret.
REPO_FIELDS = {"provider": "github", "api_uri": "https://api.github.com", "k8s_secret_name": "test-creds"}


@pytest.fixture
def test_dataset(client, user_uuid, k8s_client, mock_kc_client, project, k8s_secret):
    """Create a test dataset for repository tests"""
    dataset = Dataset(name="TestDatasetForRepo", host="example.com", k8s_secret_name=k8s_secret.name, project_id=project.id)
    dataset.add(user_id=user_uuid)
    return dataset


@pytest.fixture
def repository(client, test_dataset):
    repo = TriggerRepository(uri="github.com/org/repo", watch_dir="", project_id=test_dataset.project_id, **REPO_FIELDS)
    repo.add()
    return repo


@pytest.fixture
def repo_post_body(test_dataset):
    return {**REPO_FIELDS, "uri": "github.com/org/another-repo", "project_id": test_dataset.project_id}


class TestGetRepositories:
    def test_list_empty(self, client, simple_admin_header):
        response = client.get("/trigger_repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_returns_repos(self, client, simple_admin_header, repository):
        response = client.get("/trigger_repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert len(response.json) == 1
        assert response.json[0]["uri"] == repository.uri

    def test_get_by_id(self, client, simple_admin_header, repository):
        response = client.get(f"/trigger_repositories/{repository.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json["id"] == repository.id
        assert response.json["uri"] == repository.uri
        assert "pr_cursor" in response.json
        assert isinstance(response.json["pr_cursor"], str)
        assert response.json["base_branch"] == "main"

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/trigger_repositories/9999", headers=simple_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client):
        response = client.get("/trigger_repositories/")
        assert response.status_code == 401


class TestPostRepository:
    def test_create(self, client, simple_admin_header, post_json_admin_header, repo_post_body):
        response = client.post(
            "/trigger_repositories/",
            data=json.dumps(repo_post_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json["uri"] == repo_post_body["uri"]
        assert response.json["base_branch"] == "main"
        assert response.json["project_id"] == repo_post_body["project_id"]
        assert "pr_cursor" in response.json
        assert isinstance(response.json["pr_cursor"], str)

    def test_create_with_custom_base_branch(self, client, post_json_admin_header, test_dataset):
        body = {**REPO_FIELDS, "uri": "github.com/org/repo", "base_branch": "develop", "project_id": test_dataset.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["base_branch"] == "develop"
        assert response.json["dataset_id"] == test_dataset.id

    def test_create_normalises_uri(self, client, post_json_admin_header, test_dataset):
        body = {**REPO_FIELDS, "uri": "GitHub.com/Org/Repo/", "project_id": test_dataset.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/repo"
        assert response.json["dataset_id"] == test_dataset.id

    def test_create_duplicate_uri_fails(self, client, post_json_admin_header, repository):
        body = {**REPO_FIELDS, "uri": repository.uri, "project_id": repository.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_create_missing_uri_fails(self, client, post_json_admin_header, test_dataset):
        response = client.post("/trigger_repositories/", data=json.dumps({"project_id": test_dataset.project_id}), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_create_missing_project_id_fails(self, client, post_json_admin_header):
        response = client.post("/trigger_repositories/", data=json.dumps({"uri": "github.com/org/new-repo"}), headers=post_json_admin_header)
        assert response.status_code == 400
        assert "project_id is required" in response.json.get("error", "")

    def test_create_invalid_project_id_fails(self, client, post_json_admin_header):
        response = client.post("/trigger_repositories/", data=json.dumps({**REPO_FIELDS, "uri": "github.com/org/new-repo", "project_id": 9999}), headers=post_json_admin_header)
        assert response.status_code == 404

    def test_create_includes_dataset_id_in_response(self, client, post_json_admin_header, test_dataset):
        body = {**REPO_FIELDS, "uri": "github.com/org/test-repo", "project_id": test_dataset.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert "dataset_id" in response.json
        assert response.json["dataset_id"] == test_dataset.id

    def test_create_returns_the_git_host_and_secret(self, client, post_json_admin_header, repo_post_body):
        response = client.post("/trigger_repositories/", data=json.dumps(repo_post_body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["provider"] == "github"
        assert response.json["api_uri"] == "https://api.github.com"
        assert response.json["k8s_secret_name"] == "test-creds"

    @pytest.mark.parametrize("field", ["provider", "api_uri", "k8s_secret_name"])
    def test_create_requires_the_git_host_and_secret(self, client, post_json_admin_header, repo_post_body, field):
        del repo_post_body[field]
        response = client.post("/trigger_repositories/", data=json.dumps(repo_post_body), headers=post_json_admin_header)
        assert response.status_code == 400
        assert f"{field} is required" in response.json["error"]

    def test_create_rejects_an_unknown_provider(self, client, post_json_admin_header, repo_post_body):
        repo_post_body["provider"] = "gitlab"
        response = client.post("/trigger_repositories/", data=json.dumps(repo_post_body), headers=post_json_admin_header)
        assert response.status_code == 400
        assert "provider must be one of" in response.json["error"]

    def test_requires_auth(self, client, test_dataset):
        response = client.post("/trigger_repositories/", data=json.dumps({"uri": "x", "project_id": test_dataset.project_id}))
        assert response.status_code == 401


class TestPatchRepository:
    def test_update_base_branch(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/trigger_repositories/{repository.id}",
            data=json.dumps({"base_branch": "develop"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["base_branch"] == "develop"

    def patch(self, client, headers, repository, body):
        return client.patch(f"/trigger_repositories/{repository.id}", data=json.dumps(body), headers=headers)

    def test_update_provider_and_api_uri(self, client, post_json_admin_header, repository):
        response = self.patch(
            client, post_json_admin_header, repository,
            {"provider": "gitea", "api_uri": "http://gitea.fn.svc:3000/api/v1"}
        )
        assert response.status_code == 200
        assert response.json["provider"] == "gitea"
        assert response.json["api_uri"] == "http://gitea.fn.svc:3000/api/v1"

    def test_update_rejects_an_unknown_provider(self, client, post_json_admin_header, repository):
        response = self.patch(client, post_json_admin_header, repository, {"provider": "gitlab"})
        assert response.status_code == 400
        assert repository.provider == "github"

    def test_update_to_another_secret(self, client, post_json_admin_header, repository):
        K8sSecret(name="other-creds").add()
        response = self.patch(client, post_json_admin_header, repository, {"k8s_secret_name": "other-creds"})
        assert response.status_code == 200
        assert response.json["k8s_secret_name"] == "other-creds"

    def test_update_to_a_missing_secret_fails(self, client, post_json_admin_header, repository):
        response = self.patch(client, post_json_admin_header, repository, {"k8s_secret_name": "missing"})
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]
        assert repository.k8s_secret_name == "test-creds"

    @pytest.mark.parametrize("field", ["provider", "api_uri", "k8s_secret_name"])
    def test_git_host_fields_cannot_be_emptied(self, client, post_json_admin_header, repository, field):
        response = self.patch(client, post_json_admin_header, repository, {field: ""})
        assert response.status_code == 400
        assert f"{field} cannot be empty" in response.json["error"]

    def test_update_project_id(self, client, post_json_admin_header, repository, user_uuid, k8s_client, mock_kc_client, project):
        # Create a new dataset
        new_dataset = Dataset(name="NewDatasetForRepo", host="example.com", k8s_secret_name="test-creds", project_id=project.id)
        new_dataset.add(user_id=user_uuid)

        response = client.patch(
            f"/trigger_repositories/{repository.id}",
            data=json.dumps({"project_id": new_dataset.project_id}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["project_id"] == new_dataset.project_id

    def test_update_project_id_invalid_fails(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/trigger_repositories/{repository.id}",
            data=json.dumps({"project_id": 9999}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_empty_base_branch_fails(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/trigger_repositories/{repository.id}",
            data=json.dumps({"base_branch": ""}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_empty_body_fails(self, client, post_json_admin_header, repository):
        response = client.patch(
            f"/trigger_repositories/{repository.id}",
            data=json.dumps({}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_not_found(self, client, post_json_admin_header):
        response = client.patch(
            "/trigger_repositories/9999",
            data=json.dumps({"base_branch": "develop"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_requires_auth(self, client, repository):
        response = client.patch(f"/trigger_repositories/{repository.id}", data=json.dumps({"base_branch": "develop"}))
        assert response.status_code == 401


class TestInitialCursor:
    def test_initial_cursor_set_on_creation(self, client, post_json_admin_header, test_dataset):
        """initial_cursor should be set to current time when creating a repository"""
        response = client.post(
            "/trigger_repositories/",
            data=json.dumps({**REPO_FIELDS, "uri": "github.com/org/test-repo", "project_id": test_dataset.project_id}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert "initial_cursor" in response.json
        assert isinstance(response.json["initial_cursor"], str)

    def test_initial_cursor_custom_value(self, client, post_json_admin_header, test_dataset):
        """initial_cursor can be set to a custom value on creation"""
        custom_cursor = "2026-01-01T00:00:00"
        response = client.post(
            "/trigger_repositories/",
            data=json.dumps({**REPO_FIELDS, "uri": "github.com/org/test-repo", "project_id": test_dataset.project_id, "initial_cursor": custom_cursor}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json["initial_cursor"] == custom_cursor

    def test_pr_cursor_uses_initial_cursor(self, client, simple_admin_header, repository):
        """pr_cursor should use initial_cursor when no PRs exist"""
        response = client.get(f"/trigger_repositories/{repository.id}", headers=simple_admin_header)
        assert response.status_code == 200
        # pr_cursor should be a timestamp string matching initial_cursor behavior
        assert "pr_cursor" in response.json
        assert isinstance(response.json["pr_cursor"], str)


class TestPostPullRequestsBatch:
    def test_batch_create_multiple_prs(self, client, post_json_admin_header, repository):
        """Test creating multiple PRs in a single batch request"""
        batch_data = [
            {
                "number": 1,
                "title": "First PR",
                "raised_by": "user1",
                "merged_at": "2026-01-01T10:00:00Z",
                "merge_commit_sha": "abc123",
                "payload": {"key": "value1"}
            },
            {
                "number": 2,
                "title": "Second PR",
                "raised_by": "user2",
                "merged_at": "2026-01-02T10:00:00Z",
                "merge_commit_sha": "def456",
                "payload": {"key": "value2"}
            }
        ]
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps(batch_data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert len(response.json) == 2
        assert response.json[0]["number"] == 1
        assert response.json[1]["number"] == 2

    def test_batch_create_empty_list(self, client, post_json_admin_header, repository):
        """Test creating with empty list returns empty list"""
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps([]),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json == []

    def test_batch_exceeds_max_count(self, client, post_json_admin_header, repository):
        """Test that batch creation fails if more than 100 PRs"""
        batch_data = [
            {
                "number": i,
                "title": f"PR {i}",
                "raised_by": "user",
                "merged_at": "2026-01-01T10:00:00Z",
                "merge_commit_sha": f"sha{i}",
                "payload": {}
            }
            for i in range(101)
        ]
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps(batch_data),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "Maximum 100" in response.json.get("error", "")

    def test_batch_missing_required_field(self, client, post_json_admin_header, repository):
        """Test that batch creation fails if a PR is missing required fields"""
        batch_data = [
            {
                "number": 1,
                "title": "PR without raised_by",
                # Missing 'raised_by', 'merged_at', 'merge_commit_sha', 'payload'
                "payload": {}
            }
        ]
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps(batch_data),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_batch_invalid_status(self, client, post_json_admin_header, repository):
        """Test that batch creation fails if an invalid status is provided"""
        batch_data = [
            {
                "number": 1,
                "title": "PR with invalid status",
                "raised_by": "user",
                "merged_at": "2026-01-01T10:00:00Z",
                "merge_commit_sha": "sha1",
                "payload": {},
                "status": "INVALID_STATUS"
            }
        ]
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps(batch_data),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_batch_does_not_accept_dataset_id(self, client, post_json_admin_header, repository):
        """Test that batch PR creation ignores dataset_id in PR objects"""
        batch_data = [
            {
                "number": 1,
                "title": "PR with dataset_id",
                "raised_by": "user",
                "merged_at": "2026-01-01T10:00:00Z",
                "merge_commit_sha": "sha1",
                "payload": {},
                "dataset_id": 999  # This should be ignored
            }
        ]
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps(batch_data),
            headers=post_json_admin_header
        )
        # The batch PR endpoint should not error, dataset_id just gets ignored
        # (it's taken from the URL, not the body)
        assert response.status_code == 201
        assert len(response.json) == 1
        # Verify the PR was created with the repository_id from the URL
        assert response.json[0]["trigger_repository_id"] == repository.id

    def test_batch_not_found_repository(self, client, post_json_admin_header):
        """Test that batch PR creation fails if repository doesn't exist"""
        batch_data = [
            {
                "number": 1,
                "title": "PR",
                "raised_by": "user",
                "merged_at": "2026-01-01T10:00:00Z",
                "merge_commit_sha": "sha1",
                "payload": {}
            }
        ]
        response = client.post(
            "/trigger_repositories/9999/pull_requests/batch",
            data=json.dumps(batch_data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_batch_body_not_list(self, client, post_json_admin_header, repository):
        """Test that batch PR creation fails if body is not a list"""
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"number": 1, "title": "PR"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "must be a list" in response.json.get("error", "")


class TestTriggerRepositoryDTO:
    def test_contains_dataset_id(self, repository):
        """
        dataset_id is derived from the project's default rather than stored, because the
        Dagster sensor reads it to pick the database a task pod connects to.
        """
        sanitized = TriggerRepositoryDTO.from_model(repository).dump()
        assert "dataset_id" in sanitized
        assert sanitized["dataset_id"] == repository.project.default_dataset_id
        assert isinstance(sanitized["dataset_id"], int)

    def test_contains_project_id(self, repository):
        sanitized = TriggerRepositoryDTO.from_model(repository).dump()
        assert sanitized["project_id"] == repository.project_id

    def test_fields(self, repository):
        """Test that the DTO contains all expected fields"""
        sanitized = TriggerRepositoryDTO.from_model(repository).dump()
        expected_fields = ['id', 'uri', 'path', 'provider', 'api_uri', 'k8s_secret_name', 'watch_dir',
                           'base_branch', 'project_id', 'dataset_id', 'pr_cursor', 'pr_count']
        for field in expected_fields:
            assert field in sanitized, f"Field '{field}' missing from the DTO"

    def test_get_repository_includes_dataset_id(self, client, simple_admin_header, repository):
        """Test that GET /trigger_repositories/{id} response includes dataset_id"""
        response = client.get(f"/trigger_repositories/{repository.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert "dataset_id" in response.json
        assert response.json["dataset_id"] == repository.project.default_dataset_id

    def test_list_repositories_includes_dataset_id(self, client, simple_admin_header, repository):
        """Test that GET /trigger_repositories response includes dataset_id"""
        response = client.get("/trigger_repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert len(response.json) > 0
        assert "dataset_id" in response.json[0]
        assert response.json[0]["dataset_id"] == repository.project.default_dataset_id


@pytest.fixture
def pull_request(client, post_json_admin_header, repository):
    response = client.post(
        f"/trigger_repositories/{repository.id}/pull_requests/batch",
        data=json.dumps([{
            "number": 1,
            "title": "A PR",
            "raised_by": "user1",
            "merged_at": "2026-01-01T10:00:00Z",
            "merge_commit_sha": "a" * 40,
            "payload": {"image": "example:latest"},
        }]),
        headers=post_json_admin_header
    )
    assert response.status_code == 201
    return response.json[0]


class TestPatchPullRequest:
    @pytest.mark.parametrize("status", ["READY", "QUEUED", "STARTED", "SUCCESS", "FAILURE", "CANCELLED"])
    def test_accepts_job_statuses(
        self, client, post_json_admin_header, repository, pull_request, status
    ):
        """
        The run-status sensors still write job statuses here, and they are swallowed on
        failure, so the accepted set has to be asserted rather than watched.
        """
        response = client.patch(
            f"/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}",
            data=json.dumps({"status": status}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["status"] == status
        assert response.json["trigger_repository_id"] == repository.id

    def test_patch_payload(self, client, post_json_admin_header, repository, pull_request):
        response = client.patch(
            f"/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}",
            data=json.dumps({"payload": {"image": "other:latest"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["payload"] == {"image": "other:latest"}


class TestPostTaskRequest:
    def url(self, repository, pull_request):
        return f"/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}/task_request"

    def test_create(self, client, post_json_admin_header, repository, pull_request):
        payload = {"image": "example:latest", "env": {"KEY": "value"}}
        response = client.post(
            self.url(repository, pull_request),
            data=json.dumps({"payload": payload}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json["payload"]["image"] == "example:latest"
        assert response.json["payload"]["env"] == {"KEY": "value"}
        assert response.json["project_id"] == repository.project_id
        assert response.json["queued"] is True

    def test_create_links_to_pull_request(self, client, post_json_admin_header, repository, pull_request):
        client.post(
            self.url(repository, pull_request),
            data=json.dumps({"payload": {"image": "example:latest"}}),
            headers=post_json_admin_header
        )
        pr = PullRequest.query.filter_by(trigger_repository_id=repository.id, number=pull_request["number"]).one()
        assert pr.task_request is not None
        assert pr.task_request.project_id == repository.project_id

    def test_create_twice_conflicts(self, client, post_json_admin_header, repository, pull_request):
        url = self.url(repository, pull_request)
        body = json.dumps({"payload": {"image": "example:latest"}})
        assert client.post(url, data=body, headers=post_json_admin_header).status_code == 201
        assert client.post(url, data=body, headers=post_json_admin_header).status_code == 409

    @pytest.mark.parametrize("body", [{}, {"payload": None}, {"payload": "not-an-object"}, {"payload": []}])
    def test_create_invalid_payload_fails(self, client, post_json_admin_header, repository, pull_request, body):
        response = client.post(
            self.url(repository, pull_request),
            data=json.dumps(body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_create_pull_request_not_found(self, client, post_json_admin_header, repository):
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/999/task_request",
            data=json.dumps({"payload": {}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_create_repository_not_found(self, client, post_json_admin_header):
        response = client.post(
            "/trigger_repositories/999/pull_requests/1/task_request",
            data=json.dumps({"payload": {}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_requires_auth(self, client, repository, pull_request):
        response = client.post(
            self.url(repository, pull_request),
            data=json.dumps({"payload": {}}),
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401


class TestPostTaskRequestSpec:
    def url(self, repository, pull_request):
        return f"/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}/task_request"

    def post(self, client, headers, repository, pull_request, payload):
        return client.post(
            self.url(repository, pull_request),
            data=json.dumps({"payload": payload}),
            headers=headers
        )

    def test_payload_is_normalised(self, client, post_json_admin_header, repository, pull_request):
        response = self.post(
            client, post_json_admin_header, repository, pull_request, {"docker_image": "example:latest"}
        )
        assert response.status_code == 201
        assert response.json["payload"]["image"] == "example:latest"
        assert "docker_image" not in response.json["payload"]

    def test_pull_request_payload_is_untouched(self, client, post_json_admin_header, repository, pull_request):
        self.post(client, post_json_admin_header, repository, pull_request, {"docker_image": "example:latest"})
        pr = PullRequest.query.filter_by(trigger_repository_id=repository.id, number=pull_request["number"]).one()
        assert pr.payload == {"image": "example:latest"}

    @pytest.mark.parametrize("payload", [
        {},
        {"env": {"A": "b"}},
        {"image": "example:latest", "unknown_field": 1},
        {"image": "example:latest", "env": "not-a-dict"},
        {"image": "example:latest", "resources": {"limits": {"cpu": "abc"}}},
    ])
    def test_invalid_spec_fails(self, client, post_json_admin_header, repository, pull_request, payload):
        response = self.post(client, post_json_admin_header, repository, pull_request, payload)
        assert response.status_code == 400

    def test_dataset_default_is_used(self, client, post_json_admin_header, repository, pull_request):
        response = self.post(client, post_json_admin_header, repository, pull_request, {"image": "example:latest"})
        assert response.status_code == 201
        assert response.json["payload"]["dataset"] is None

    def test_dataset_override_in_same_project(
            self, client, post_json_admin_header, repository, pull_request, project, k8s_secret, user_uuid
        ):
        second_ds = Dataset(
            name="SecondDs", host="example.com", k8s_secret_name=k8s_secret.name, project_id=project.id
        )
        second_ds.add(user_id=user_uuid)
        payload = {"image": "example:latest", "dataset": second_ds.name}
        response = self.post(client, post_json_admin_header, repository, pull_request, payload)
        assert response.status_code == 201
        assert response.json["payload"]["dataset"] == second_ds.name

    def test_dataset_override_in_other_project_fails(
            self, client, post_json_admin_header, repository, pull_request, other_project, k8s_secret, user_uuid
        ):
        other_ds = Dataset(
            name="OtherDs", host="example.com", k8s_secret_name=k8s_secret.name, project_id=other_project.id
        )
        other_ds.add(user_id=user_uuid)
        payload = {"image": "example:latest", "dataset": other_ds.name}
        response = self.post(client, post_json_admin_header, repository, pull_request, payload)
        assert response.status_code == 400
        assert "does not belong to project" in response.json["error"]

    def test_no_dataset_and_no_default_fails(
            self, client, post_json_admin_header, repository, pull_request, project
        ):
        project.default_dataset_id = None
        project.add()
        response = self.post(client, post_json_admin_header, repository, pull_request, {"image": "example:latest"})
        assert response.status_code == 400
        assert "has no default dataset" in response.json["error"]


class TestPullRequestDTO:
    def test_fields(self, pull_request):
        """Dagster's PullRequest wire model requires these"""
        expected_fields = ['trigger_repository_id', 'number', 'title', 'raised_by', 'merged_at',
                           'payload', 'merge_commit_sha', 'status']
        for field in expected_fields:
            assert field in pull_request, f"Field '{field}' missing from the DTO"

    def test_values(self, repository, pull_request):
        assert pull_request["trigger_repository_id"] == repository.id
        assert pull_request["payload"] == {"image": "example:latest"}
        assert pull_request["status"] == "UNKNOWN"

    def test_datetimes_are_iso_strings(self, pull_request):
        assert pull_request["merged_at"] == "2026-01-01T10:00:00"
        assert isinstance(pull_request["saved_at"], str)


class TestTaskRequestDTO:
    def test_fields(self, client, post_json_admin_header, repository, pull_request):
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}/task_request",
            data=json.dumps({"payload": {"image": "example:latest"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert set(response.json) == {
            'id', 'pull_request_id', 'api_request_id', 'project_id', 'queued', 'payload'
        }
        assert response.json["api_request_id"] is None
