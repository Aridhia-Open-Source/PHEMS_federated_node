import json
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.dtos.task_result import PullRequestResultDTO
from app.models.pull_request_result import PullRequestResult
from app.models.results_repository import ResultsRepository
from app.models.task_result import TaskResult
from app.models.task_result_status import TaskResultStatus


@pytest.fixture
def task(make_task):
    return make_task()


@pytest.fixture
def results_repo(client, project, secret):
    repo = ResultsRepository(
        uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
        secret_id=secret.id, target_dir="results", project_id=project.id
    )
    repo.add()
    return repo


@pytest.fixture
def task_result(task, results_repo):
    task_result = PullRequestResult(task_id=task.id, results_repository_id=results_repo.id)
    task_result.add()
    return task_result


class TestTaskResultModel:
    def test_status_values(self):
        assert [s.value for s in TaskResultStatus] == [
            "PENDING", "PUSHED", "PR_OPENED", "DELIVERED", "FAILED"
        ]

    def test_defaults(self, task_result):
        assert task_result.status == TaskResultStatus.PENDING.value
        assert task_result.attempts == 0
        assert task_result.type == "PR"
        assert task_result.branch is None
        assert task_result.merge_status is None
        assert task_result.created_at is not None

    def test_base_query_returns_the_child(self, task_result):
        assert isinstance(TaskResult.query.get(task_result.id), PullRequestResult)

    def test_unique_per_task_and_destination(self, task, results_repo, task_result):
        with pytest.raises(IntegrityError):
            PullRequestResult(task_id=task.id, results_repository_id=results_repo.id).add()

    def test_results_relationship(self, task, task_result):
        assert task.results == [task_result]

    def test_results_repository_with_results_cannot_be_deleted(self, results_repo, task_result):
        with pytest.raises(IntegrityError):
            results_repo.delete()


class TestGetTaskResults:
    def test_list_empty(self, client, simple_admin_header, task):
        response = client.get(f"/tasks/{task.id}/results", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list(self, client, simple_admin_header, task, task_result):
        response = client.get(f"/tasks/{task.id}/results", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == [PullRequestResultDTO.from_model(task_result).dump()]
        assert response.json[0]["status"] == "PENDING"
        assert response.json[0]["type"] == "PR"
        assert response.json[0]["merge_status"] is None

    def test_list_unknown_task(self, client, simple_admin_header):
        response = client.get("/tasks/9999/results", headers=simple_admin_header)
        assert response.status_code == 404

    def test_get_by_id(self, client, simple_admin_header, task_result):
        response = client.get(f"/task_results/{task_result.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == PullRequestResultDTO.from_model(task_result).dump()

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/task_results/9999", headers=simple_admin_header)
        assert response.status_code == 404

    def test_list_all(self, client, simple_admin_header, task_result):
        response = client.get("/task_results", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == [PullRequestResultDTO.from_model(task_result).dump()]

    def test_list_by_merge_status(self, client, simple_admin_header, make_task, results_repo, task_result):
        open_result = PullRequestResult(task_id=make_task().id, results_repository_id=results_repo.id)
        open_result.merge_status = "OPEN"
        open_result.add()
        response = client.get("/task_results?merge_status=OPEN", headers=simple_admin_header)
        assert response.status_code == 200
        assert [r["id"] for r in response.json] == [open_result.id]

    def test_list_invalid_merge_status(self, client, simple_admin_header):
        response = client.get("/task_results?merge_status=open", headers=simple_admin_header)
        assert response.status_code == 400


class TestPostTaskResult:
    def post(self, client, headers, body):
        return client.post("/task_results", data=json.dumps(body), headers=headers)

    def test_create(self, client, post_json_admin_header, task, results_repo):
        response = self.post(
            client, post_json_admin_header, {"task_id": task.id, "results_repository_id": results_repo.id}
        )
        assert response.status_code == 201
        assert response.json["task_id"] == task.id
        assert response.json["results_repository_id"] == results_repo.id
        assert response.json["status"] == "PENDING"
        assert response.json["attempts"] == 0
        assert response.json["type"] == "PR"
        assert isinstance(TaskResult.query.filter_by(task_id=task.id).one(), PullRequestResult)

    def test_create_is_idempotent(self, client, post_json_admin_header, task, results_repo, task_result):
        response = self.post(
            client, post_json_admin_header, {"task_id": task.id, "results_repository_id": results_repo.id}
        )
        assert response.status_code == 200
        assert response.json == PullRequestResultDTO.from_model(task_result).dump()
        assert TaskResult.query.filter_by(task_id=task.id).count() == 1

    def test_unknown_task(self, client, post_json_admin_header, results_repo):
        response = self.post(
            client, post_json_admin_header, {"task_id": 9999, "results_repository_id": results_repo.id}
        )
        assert response.status_code == 404

    def test_unknown_repository(self, client, post_json_admin_header, task):
        response = self.post(client, post_json_admin_header, {"task_id": task.id, "results_repository_id": 9999})
        assert response.status_code == 404

    @pytest.mark.parametrize("body", [{}, {"task_id": 1}, {"results_repository_id": 1}, {"task_id": "1", "results_repository_id": 1}])
    def test_invalid_body(self, client, post_json_admin_header, body):
        response = self.post(client, post_json_admin_header, body)
        assert response.status_code == 400


class TestPatchTaskResult:
    def patch(self, client, headers, task_result_id, body):
        return client.patch(f"/task_results/{task_result_id}", data=json.dumps(body), headers=headers)

    def test_update_all_fields(self, client, post_json_admin_header, task_result):
        response = self.patch(client, post_json_admin_header, task_result.id, {
            "status": "PR_OPENED", "attempts": 2, "branch": "task-1-results", "commit_sha": "a" * 40,
            "number": 7, "url": "https://example.com/pull/7", "error": None,
            "merge_status": "MERGED", "merged_at": "2026-10-08T10:30:00Z", "merge_commit_sha": "b" * 40,
        })
        assert response.status_code == 200
        assert response.json["status"] == "PR_OPENED"
        assert response.json["attempts"] == 2
        assert response.json["branch"] == "task-1-results"
        assert response.json["commit_sha"] == "a" * 40
        assert response.json["number"] == 7
        assert response.json["url"] == "https://example.com/pull/7"
        assert response.json["merge_status"] == "MERGED"
        assert response.json["merged_at"] == "2026-10-08T10:30:00"
        assert response.json["merge_commit_sha"] == "b" * 40
        task_result = TaskResult.query.get(task_result.id)
        assert task_result.status == "PR_OPENED"
        assert task_result.attempts == 2
        assert task_result.merged_at == datetime(2026, 10, 8, 10, 30)

    def test_update_failed_with_error(self, client, post_json_admin_header, task_result):
        response = self.patch(client, post_json_admin_header, task_result.id, {"status": "FAILED", "error": "zip too big"})
        assert response.status_code == 200
        task_result = TaskResult.query.get(task_result.id)
        assert task_result.status == "FAILED"
        assert task_result.error == "zip too big"
        assert task_result.commit_sha is None

    def test_not_found(self, client, post_json_admin_header):
        response = self.patch(client, post_json_admin_header, 9999, {"status": "DELIVERED"})
        assert response.status_code == 404

    @pytest.mark.parametrize("body", [
        {},
        {"status": "delivered"},
        {"status": "DONE"},
        {"task_id": 2},
        {"attempts": "1"},
        {"attempts": True},
        {"number": "7"},
        {"commit_sha": "a" * 41},
        {"error": 1},
        {"branch": 1},
        {"merge_status": "open"},
        {"merge_status": None},
        {"merged_at": "yesterday"},
        {"merged_at": 1},
        {"merge_commit_sha": "b" * 41},
    ])
    def test_invalid_body(self, client, post_json_admin_header, task_result, body):
        response = self.patch(client, post_json_admin_header, task_result.id, body)
        assert response.status_code == 400
        assert TaskResult.query.get(task_result.id).status == "PENDING"


class TestTaskResultWritesAuth:
    @pytest.fixture
    def tasks_kc(self, mock_kc_client):
        kc = mock_kc_client["tasks_api_kc"].return_value
        kc.is_user_admin.return_value = False
        kc.is_system_user.return_value = False
        return kc

    def test_the_system_user_writes(self, client, post_json_admin_header, make_task, results_repo, tasks_kc):
        tasks_kc.is_system_user.return_value = True
        task = make_task(requested_by="someone-else")
        response = client.post(
            "/task_results", headers=post_json_admin_header,
            data=json.dumps({"task_id": task.id, "results_repository_id": results_repo.id})
        )
        assert response.status_code == 201

    def test_another_user_is_forbidden(self, client, post_json_admin_header, make_task, results_repo, tasks_kc):
        task = make_task(requested_by="someone-else")
        response = client.post(
            "/task_results", headers=post_json_admin_header,
            data=json.dumps({"task_id": task.id, "results_repository_id": results_repo.id})
        )
        assert response.status_code == 403

    def test_patch_by_another_user_is_forbidden(self, client, post_json_admin_header, task_result, tasks_kc):
        task_result.task.requested_by = "someone-else"
        task_result.add()
        response = client.patch(
            f"/task_results/{task_result.id}", headers=post_json_admin_header,
            data=json.dumps({"status": "DELIVERED"})
        )
        assert response.status_code == 403
