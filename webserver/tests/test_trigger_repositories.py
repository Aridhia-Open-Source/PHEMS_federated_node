import json
import pytest
from app.models.trigger_repository import TriggerRepository
from app.models.dataset import Dataset


@pytest.fixture
def test_dataset(client, user_uuid, k8s_client, mock_kc_client, project):
    """Create a test dataset for repository tests"""
    dataset = Dataset(name="TestDatasetForRepo", host="example.com", password='pass', username='user', project_id=project.id)
    dataset.add(user_id=user_uuid)
    return dataset


@pytest.fixture
def repository(client, test_dataset):
    repo = TriggerRepository(uri="github.com/org/repo", watch_dir="", project_id=test_dataset.project_id)
    repo.add()
    return repo


@pytest.fixture
def repo_post_body(test_dataset):
    return {"uri": "github.com/org/another-repo", "project_id": test_dataset.project_id}


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
        body = {"uri": "github.com/org/repo", "base_branch": "develop", "project_id": test_dataset.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["base_branch"] == "develop"
        assert response.json["dataset_id"] == test_dataset.id

    def test_create_normalises_uri(self, client, post_json_admin_header, test_dataset):
        body = {"uri": "GitHub.com/Org/Repo/", "project_id": test_dataset.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/repo"
        assert response.json["dataset_id"] == test_dataset.id

    def test_create_duplicate_uri_fails(self, client, post_json_admin_header, repository):
        body = {"uri": repository.uri, "project_id": repository.project_id}
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
        response = client.post("/trigger_repositories/", data=json.dumps({"uri": "github.com/org/new-repo", "project_id": 9999}), headers=post_json_admin_header)
        assert response.status_code == 404

    def test_create_includes_dataset_id_in_response(self, client, post_json_admin_header, test_dataset):
        body = {"uri": "github.com/org/test-repo", "project_id": test_dataset.project_id}
        response = client.post("/trigger_repositories/", data=json.dumps(body), headers=post_json_admin_header)
        assert response.status_code == 201
        assert "dataset_id" in response.json
        assert response.json["dataset_id"] == test_dataset.id

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

    def test_update_project_id(self, client, post_json_admin_header, repository, user_uuid, k8s_client, mock_kc_client, project):
        # Create a new dataset
        new_dataset = Dataset(name="NewDatasetForRepo", host="example.com", password='pass', username='user', project_id=project.id)
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
            data=json.dumps({"uri": "github.com/org/test-repo", "project_id": test_dataset.project_id}),
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
            data=json.dumps({"uri": "github.com/org/test-repo", "project_id": test_dataset.project_id, "initial_cursor": custom_cursor}),
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
                "spec": {"key": "value1"}
            },
            {
                "number": 2,
                "title": "Second PR",
                "raised_by": "user2",
                "merged_at": "2026-01-02T10:00:00Z",
                "merge_commit_sha": "def456",
                "spec": {"key": "value2"}
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
                "spec": {}
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
                # Missing 'raised_by', 'merged_at', 'merge_commit_sha', 'spec'
                "spec": {}
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
                "spec": {},
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
                "spec": {},
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
                "spec": {}
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


class TestRepositorySanitizedDict:
    def test_sanitized_dict_contains_dataset_id(self, repository):
        """
        dataset_id is derived from the project's default rather than stored, because the
        Dagster sensor reads it to pick the database a task pod connects to.
        """
        sanitized = repository.sanitized_dict()
        assert "dataset_id" in sanitized
        assert sanitized["dataset_id"] == repository.project.default_dataset_id
        assert isinstance(sanitized["dataset_id"], int)

    def test_sanitized_dict_contains_project_id(self, repository):
        sanitized = repository.sanitized_dict()
        assert sanitized["project_id"] == repository.project_id

    def test_sanitized_dict_fields(self, repository):
        """Test that sanitized_dict() contains all expected fields"""
        sanitized = repository.sanitized_dict()
        expected_fields = ['id', 'uri', 'path', 'watch_dir', 'base_branch', 'project_id',
                           'dataset_id', 'pr_cursor', 'pr_count']
        for field in expected_fields:
            assert field in sanitized, f"Field '{field}' missing from sanitized_dict()"

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


class TestPatchPullRequest:
    @pytest.fixture
    def pull_request(self, client, post_json_admin_header, repository):
        response = client.post(
            f"/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps([{
                "number": 1,
                "title": "A PR",
                "raised_by": "user1",
                "merged_at": "2026-01-01T10:00:00Z",
                "merge_commit_sha": "a" * 40,
                "spec": {"image": "example:latest"},
            }]),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        return response.json[0]

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
