import json
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.dtos.result import PullRequestResultDTO
from app.models.pull_request_result import PullRequestResult
from app.models.results_repository import ResultsRepository
from app.models.result import Result
from app.models.pull_request_result_state import PullRequestResultState


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
def result(task, results_repo):
    result = PullRequestResult(task_id=task.id, results_repository_id=results_repo.id)
    result.add()
    return result


def make_result(make_task, results_repo, state):
    result = PullRequestResult(task_id=make_task().id, results_repository_id=results_repo.id)
    result.state = state
    result.add()
    return result


class TestResultModel:
    def test_state_values(self):
        assert [s.value for s in PullRequestResultState] == [
            "UNKNOWN", "PUSHED", "OPENED", "MERGED", "CLOSED"
        ]

    def test_defaults(self, result):
        assert result.state == PullRequestResultState.UNKNOWN.value
        assert result.attempts == 0
        assert result.type == "PR"
        assert result.branch is None
        assert result.created_at is not None

    def test_base_query_returns_the_child(self, result):
        assert isinstance(Result.query.get(result.id), PullRequestResult)

    def test_unique_per_task_and_destination(self, task, results_repo, result):
        with pytest.raises(IntegrityError):
            PullRequestResult(task_id=task.id, results_repository_id=results_repo.id).add()

    def test_results_relationship(self, task, result):
        assert task.results == [result]

    def test_results_repository_with_results_cannot_be_deleted(self, results_repo, result):
        with pytest.raises(IntegrityError):
            results_repo.delete()


class TestGetResults:
    def test_list_empty(self, client, simple_admin_header, task):
        response = client.get(f"/tasks/{task.id}/results", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list(self, client, simple_admin_header, task, result):
        response = client.get(f"/tasks/{task.id}/results", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == [PullRequestResultDTO.from_model(result).dump()]
        assert response.json[0]["state"] == "UNKNOWN"
        assert response.json[0]["type"] == "PR"

    def test_list_unknown_task(self, client, simple_admin_header):
        response = client.get("/tasks/9999/results", headers=simple_admin_header)
        assert response.status_code == 404

    def test_get_by_id(self, client, simple_admin_header, result):
        response = client.get(f"/results/{result.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == PullRequestResultDTO.from_model(result).dump()

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/results/9999", headers=simple_admin_header)
        assert response.status_code == 404

    def test_list_all(self, client, simple_admin_header, result):
        response = client.get("/results", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == [PullRequestResultDTO.from_model(result).dump()]

    def test_list_by_state(self, client, simple_admin_header, make_task, results_repo, result):
        opened = make_result(make_task, results_repo, "OPENED")
        response = client.get("/results?state=OPENED", headers=simple_admin_header)
        assert response.status_code == 200
        assert [r["id"] for r in response.json] == [opened.id]

    def test_list_by_several_states(self, client, simple_admin_header, make_task, results_repo, result):
        pushed = make_result(make_task, results_repo, "PUSHED")
        opened = make_result(make_task, results_repo, "OPENED")
        make_result(make_task, results_repo, "MERGED")
        make_result(make_task, results_repo, "CLOSED")
        response = client.get("/results?state=PUSHED&state=OPENED", headers=simple_admin_header)
        assert response.status_code == 200
        assert [r["id"] for r in response.json] == [pushed.id, opened.id]

    @pytest.mark.parametrize("query", ["state=opened", "state=OPEN", "state=OPENED&state=DELIVERED"])
    def test_list_invalid_state(self, client, simple_admin_header, query):
        response = client.get(f"/results?{query}", headers=simple_admin_header)
        assert response.status_code == 400


class TestPostResult:
    def post(self, client, headers, body):
        return client.post("/results", data=json.dumps(body), headers=headers)

    def test_create(self, client, post_json_admin_header, task, results_repo):
        response = self.post(
            client, post_json_admin_header, {"task_id": task.id, "results_repository_id": results_repo.id}
        )
        assert response.status_code == 201
        assert response.json["task_id"] == task.id
        assert response.json["results_repository_id"] == results_repo.id
        assert response.json["state"] == "UNKNOWN"
        assert response.json["attempts"] == 0
        assert response.json["type"] == "PR"
        assert isinstance(Result.query.filter_by(task_id=task.id).one(), PullRequestResult)

    def test_create_is_idempotent(self, client, post_json_admin_header, task, results_repo, result):
        response = self.post(
            client, post_json_admin_header, {"task_id": task.id, "results_repository_id": results_repo.id}
        )
        assert response.status_code == 200
        assert response.json == PullRequestResultDTO.from_model(result).dump()
        assert Result.query.filter_by(task_id=task.id).count() == 1

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


class TestPatchResult:
    def patch(self, client, headers, result_id, body):
        return client.patch(f"/results/{result_id}", data=json.dumps(body), headers=headers)

    def test_update_all_fields(self, client, post_json_admin_header, result):
        response = self.patch(client, post_json_admin_header, result.id, {
            "state": "MERGED", "attempts": 2, "branch": "task-1-results", "commit_sha": "a" * 40,
            "number": 7, "url": "https://example.com/pull/7", "error": None,
            "merged_at": "2026-10-08T10:30:00Z", "merge_commit_sha": "b" * 40,
        })
        assert response.status_code == 200
        assert response.json["state"] == "MERGED"
        assert response.json["attempts"] == 2
        assert response.json["branch"] == "task-1-results"
        assert response.json["commit_sha"] == "a" * 40
        assert response.json["number"] == 7
        assert response.json["url"] == "https://example.com/pull/7"
        assert response.json["merged_at"] == "2026-10-08T10:30:00"
        assert response.json["merge_commit_sha"] == "b" * 40
        result = Result.query.get(result.id)
        assert result.state == "MERGED"
        assert result.attempts == 2
        assert result.merged_at == datetime(2026, 10, 8, 10, 30)

    def test_a_failure_keeps_the_state(self, client, post_json_admin_header, result):
        response = self.patch(client, post_json_admin_header, result.id, {"attempts": 1, "error": "zip too big"})
        assert response.status_code == 200
        result = Result.query.get(result.id)
        assert result.state == "UNKNOWN"
        assert result.attempts == 1
        assert result.error == "zip too big"
        assert result.commit_sha is None

    @pytest.mark.parametrize("current,new", [
        ("UNKNOWN", "PUSHED"), ("UNKNOWN", "OPENED"), ("UNKNOWN", "MERGED"),
        ("PUSHED", "OPENED"), ("PUSHED", "MERGED"), ("PUSHED", "CLOSED"),
        ("OPENED", "MERGED"), ("OPENED", "CLOSED"),
    ])
    def test_state_moves_forward(self, client, post_json_admin_header, make_task, results_repo, current, new):
        result = make_result(make_task, results_repo, current)
        response = self.patch(client, post_json_admin_header, result.id, {"state": new})
        assert response.status_code == 200
        assert Result.query.get(result.id).state == new

    @pytest.mark.parametrize("state", ["UNKNOWN", "PUSHED", "OPENED", "MERGED", "CLOSED"])
    def test_same_state_is_allowed(self, client, post_json_admin_header, make_task, results_repo, state):
        result = make_result(make_task, results_repo, state)
        response = self.patch(client, post_json_admin_header, result.id, {"state": state, "attempts": 3})
        assert response.status_code == 200
        assert Result.query.get(result.id).state == state
        assert Result.query.get(result.id).attempts == 3

    @pytest.mark.parametrize("current,new", [
        ("PUSHED", "UNKNOWN"),
        ("OPENED", "UNKNOWN"), ("OPENED", "PUSHED"),
        ("MERGED", "UNKNOWN"), ("MERGED", "PUSHED"), ("MERGED", "OPENED"), ("MERGED", "CLOSED"),
        ("CLOSED", "UNKNOWN"), ("CLOSED", "PUSHED"), ("CLOSED", "OPENED"), ("CLOSED", "MERGED"),
    ])
    def test_state_cannot_move_back(self, client, post_json_admin_header, make_task, results_repo, current, new):
        result = make_result(make_task, results_repo, current)
        response = self.patch(client, post_json_admin_header, result.id, {"state": new, "number": 7})
        assert response.status_code == 400
        assert Result.query.get(result.id).state == current
        assert Result.query.get(result.id).number is None

    def test_not_found(self, client, post_json_admin_header):
        response = self.patch(client, post_json_admin_header, 9999, {"state": "PUSHED"})
        assert response.status_code == 404

    @pytest.mark.parametrize("body", [
        {},
        {"state": "pushed"},
        {"state": "DELIVERED"},
        {"state": None},
        {"status": "PUSHED"},
        {"merge_status": "OPEN"},
        {"task_id": 2},
        {"attempts": "1"},
        {"attempts": True},
        {"number": "7"},
        {"commit_sha": "a" * 41},
        {"error": 1},
        {"branch": 1},
        {"merged_at": "yesterday"},
        {"merged_at": 1},
        {"merge_commit_sha": "b" * 41},
    ])
    def test_invalid_body(self, client, post_json_admin_header, result, body):
        response = self.patch(client, post_json_admin_header, result.id, body)
        assert response.status_code == 400
        assert Result.query.get(result.id).state == "UNKNOWN"


class TestResultWritesAuth:
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
            "/results", headers=post_json_admin_header,
            data=json.dumps({"task_id": task.id, "results_repository_id": results_repo.id})
        )
        assert response.status_code == 201

    def test_another_user_is_forbidden(self, client, post_json_admin_header, make_task, results_repo, tasks_kc):
        task = make_task(requested_by="someone-else")
        response = client.post(
            "/results", headers=post_json_admin_header,
            data=json.dumps({"task_id": task.id, "results_repository_id": results_repo.id})
        )
        assert response.status_code == 403

    def test_patch_by_another_user_is_forbidden(self, client, post_json_admin_header, result, tasks_kc):
        result.task.requested_by = "someone-else"
        result.add()
        response = client.patch(
            f"/results/{result.id}", headers=post_json_admin_header,
            data=json.dumps({"state": "PUSHED"})
        )
        assert response.status_code == 403
