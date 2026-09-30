import json
import pytest

from app.models.api_request import ApiRequest
from app.models.pull_request import PullRequest
from app.models.task import Task
from app.models.task_request import TaskRequest

SPEC = {
    "name": "TestTask", "description": None, "image": "img:1", "command": None, "env": {},
    "params": {}, "dataset": None, "tags": {}, "resources": {}, "repository": None,
}


@pytest.fixture
def pull_request(client, default_repo):
    pull_request = PullRequest(
        trigger_repository_id=default_repo.id, number=7, title="PR title", raised_by="pr-author",
        merged_at="2026-01-01T10:00:00", merge_commit_sha="a" * 40, payload={"image": "img:1"},
    )
    pull_request.add()
    return pull_request


@pytest.fixture
def pr_task_request(pull_request, project):
    task_request = TaskRequest(
        pull_request_id=pull_request.id, project_id=project.id, payload={**SPEC, "name": None}, queued=True
    )
    task_request.add()
    return task_request


@pytest.fixture
def api_task_request(client, project, default_repo):
    api_request = ApiRequest(project_id=project.id, user_id="api-user", payload={"raw": True})
    api_request.add()
    task_request = TaskRequest(api_request_id=api_request.id, project_id=project.id, payload=dict(SPEC))
    task_request.add()
    return task_request


@pytest.fixture
def other_project_task_request(client, other_project):
    api_request = ApiRequest(project_id=other_project.id, user_id="api-user")
    api_request.add()
    task_request = TaskRequest(
        api_request_id=api_request.id, project_id=other_project.id, payload=dict(SPEC), queued=True
    )
    task_request.add()
    return task_request


@pytest.fixture
def forbidden(mock_kc_client):
    is_token_valid = mock_kc_client["wrappers_kc"].return_value.is_token_valid
    is_token_valid.side_effect = None
    is_token_valid.return_value = False


class TestGetTaskRequests:
    def test_list(self, client, simple_admin_header, pr_task_request, api_task_request):
        response = client.get("/task_requests", headers=simple_admin_header)
        assert response.status_code == 200
        assert set(response.json) == {"items", "page", "per_page", "total", "pages"}
        assert [tr["id"] for tr in response.json["items"]] == [pr_task_request.id, api_task_request.id]

    @pytest.mark.parametrize("queued, expected", [("true", "pr_task_request"), ("false", "api_task_request")])
    def test_filter_queued(
            self, client, simple_admin_header, pr_task_request, api_task_request, queued, expected, request
        ):
        response = client.get(f"/task_requests?queued={queued}", headers=simple_admin_header)
        assert response.status_code == 200
        assert [tr["id"] for tr in response.json["items"]] == [request.getfixturevalue(expected).id]

    def test_filter_invalid_queued(self, client, simple_admin_header):
        response = client.get("/task_requests?queued=yes", headers=simple_admin_header)
        assert response.status_code == 400

    def test_filter_project_id(
            self, client, simple_admin_header, pr_task_request, other_project_task_request, other_project
        ):
        response = client.get(f"/task_requests?project_id={other_project.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert [tr["id"] for tr in response.json["items"]] == [other_project_task_request.id]

    def test_filters_combine(
            self, client, simple_admin_header, pr_task_request, api_task_request, other_project_task_request, project
        ):
        response = client.get(f"/task_requests?queued=true&project_id={project.id}", headers=simple_admin_header)
        assert [tr["id"] for tr in response.json["items"]] == [pr_task_request.id]

    def test_paginated(self, client, simple_admin_header, pr_task_request, api_task_request):
        response = client.get("/task_requests?page=2&per_page=1", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json["total"] == 2
        assert response.json["pages"] == 2
        assert [tr["id"] for tr in response.json["items"]] == [api_task_request.id]

    def test_requires_auth(self, client):
        response = client.get("/task_requests")
        assert response.status_code == 401

    def test_forbidden(self, client, simple_user_header, forbidden):
        response = client.get("/task_requests", headers=simple_user_header)
        assert response.status_code == 403


class TestGetTaskRequest:
    def test_get(self, client, simple_admin_header, pr_task_request):
        response = client.get(f"/task_requests/{pr_task_request.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json["id"] == pr_task_request.id
        assert response.json["pull_request_id"] == pr_task_request.pull_request_id
        assert response.json["queued"] is True

    def test_not_found(self, client, simple_admin_header):
        response = client.get("/task_requests/999", headers=simple_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client, pr_task_request):
        response = client.get(f"/task_requests/{pr_task_request.id}")
        assert response.status_code == 401


class TestPatchTaskRequest:
    def test_update_queued(self, client, post_json_admin_header, pr_task_request):
        response = client.patch(
            f"/task_requests/{pr_task_request.id}",
            data=json.dumps({"queued": False}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["queued"] is False
        assert TaskRequest.query.get(pr_task_request.id).queued is False

    @pytest.mark.parametrize("body", [{}, {"payload": {}}])
    def test_no_queued_fails(self, client, post_json_admin_header, pr_task_request, body):
        response = client.patch(
            f"/task_requests/{pr_task_request.id}",
            data=json.dumps(body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_queued_not_bool_fails(self, client, post_json_admin_header, pr_task_request):
        response = client.patch(
            f"/task_requests/{pr_task_request.id}",
            data=json.dumps({"queued": "false"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_not_found(self, client, post_json_admin_header):
        response = client.patch("/task_requests/999", data=json.dumps({"queued": False}), headers=post_json_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client, pr_task_request):
        response = client.patch(
            f"/task_requests/{pr_task_request.id}",
            data=json.dumps({"queued": False}),
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401


class TestPostTask:
    def test_create_from_pull_request(self, client, post_json_admin_header, pr_task_request, pull_request):
        response = client.post(f"/task_requests/{pr_task_request.id}/task", headers=post_json_admin_header)
        assert response.status_code == 201
        task = Task.query.one()
        assert response.json["id"] == task.id
        assert task.task_request_id == pr_task_request.id
        assert task.requested_by == "pr-author"
        assert task.name == "PR title"
        assert task.pr_number == pull_request.number

    def test_create_from_api_request(self, client, post_json_admin_header, api_task_request):
        response = client.post(f"/task_requests/{api_task_request.id}/task", headers=post_json_admin_header)
        assert response.status_code == 201
        task = Task.query.one()
        assert task.requested_by == "api-user"
        assert task.api_request_id == api_task_request.api_request_id

    def test_create_is_idempotent(self, client, post_json_admin_header, pr_task_request):
        url = f"/task_requests/{pr_task_request.id}/task"
        first = client.post(url, headers=post_json_admin_header)
        second = client.post(url, headers=post_json_admin_header)
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json["id"] == first.json["id"]
        assert Task.query.count() == 1

    def test_no_dataset_fails(self, client, post_json_admin_header, pr_task_request, project):
        project.default_dataset_id = None
        project.add()
        response = client.post(f"/task_requests/{pr_task_request.id}/task", headers=post_json_admin_header)
        assert response.status_code == 400
        assert Task.query.count() == 0

    def test_not_found(self, client, post_json_admin_header):
        response = client.post("/task_requests/999/task", headers=post_json_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client, pr_task_request):
        response = client.post(f"/task_requests/{pr_task_request.id}/task")
        assert response.status_code == 401

    def test_forbidden(self, client, post_json_user_header, pr_task_request, forbidden):
        response = client.post(f"/task_requests/{pr_task_request.id}/task", headers=post_json_user_header)
        assert response.status_code == 403
        assert Task.query.count() == 0


class TestPullRequestToTask:
    def test_end_to_end(self, client, post_json_admin_header, simple_admin_header, default_repo, project):
        # The pull request is recorded, then normalised into a queued task request
        response = client.post(
            f"/trigger_repositories/{default_repo.id}/pull_requests/batch",
            data=json.dumps([{
                "number": 3, "title": "Run analysis", "raised_by": "pr-author",
                "merged_at": "2026-01-01T10:00:00Z", "merge_commit_sha": "b" * 40,
                "payload": {"docker_image": "img:1"},
            }]),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        response = client.post(
            f"/trigger_repositories/{default_repo.id}/pull_requests/3/task_request",
            data=json.dumps({"payload": {"docker_image": "img:1"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

        # The launcher finds it among the queued requests
        response = client.get(f"/task_requests?queued=true&project_id={project.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert len(response.json["items"]) == 1
        task_request_id = response.json["items"][0]["id"]

        response = client.post(f"/task_requests/{task_request_id}/task", headers=post_json_admin_header)
        assert response.status_code == 201
        task_id = response.json["id"]
        assert response.json["docker_image"] == "img:1"
        assert response.json["requested_by"] == "pr-author"
        assert response.json["dataset_id"] == project.default_dataset_id

        response = client.patch(
            f"/task_requests/{task_request_id}", data=json.dumps({"queued": False}), headers=post_json_admin_header
        )
        assert response.status_code == 200
        response = client.patch(
            f"/tasks/{task_id}",
            data=json.dumps({"status": "RUNNING", "dagster_run_id": "run-1", "started_at": "2026-01-01T10:05:00"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        response = client.patch(
            f"/tasks/{task_id}",
            data=json.dumps({"status": "SUCCESS", "exit_code": 0, "completed_at": "2026-01-01T10:10:00"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["status"] == "SUCCESS"

        response = client.get("/task_requests?queued=true", headers=simple_admin_header)
        assert response.json["items"] == []
        task = Task.query.get(task_id)
        assert task.task_request_id == task_request_id
        assert task.dagster_run_id == "run-1"
        assert task.exit_code == 0
        assert task.started_at.isoformat() == "2026-01-01T10:05:00"
        assert task.completed_at.isoformat() == "2026-01-01T10:10:00"
