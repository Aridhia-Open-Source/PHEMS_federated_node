import json
import pytest

from app.models.task import Task


@pytest.fixture
def task(make_task, dataset):
    return make_task(dataset_id=dataset.id)


class TestPatchTask:
    def patch(self, client, headers, project, task_id, body):
        return client.patch(f"/projects/{project.id}/tasks/{task_id}", data=json.dumps(body), headers=headers)

    def test_update_all_fields(self, client, system_headers, task, project):
        response = self.patch(client, system_headers, project, task.id, {
            "status": "FAILED", "executor_run_id": "run-1", "exit_code": 2,
            "started_at": "2026-01-01T10:00:00Z", "completed_at": "2026-01-01T10:30:00",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "FAILED"
        assert response.json()["executor_run_id"] == "run-1"
        assert response.json()["exit_code"] == 2
        assert response.json()["started_at"] == "2026-01-01 10:00:00"
        assert response.json()["completed_at"] == "2026-01-01 10:30:00"
        task = Task.query.get(task.id)
        assert task.status == "FAILED"
        assert task.executor_run_id == "run-1"
        assert task.exit_code == 2
        assert task.started_at.isoformat() == "2026-01-01T10:00:00"
        assert task.completed_at.isoformat() == "2026-01-01T10:30:00"

    def test_update_status_only(self, client, system_headers, task, project):
        response = self.patch(client, system_headers, project, task.id, {"status": "RUNNING"})
        assert response.status_code == 200
        task = Task.query.get(task.id)
        assert task.status == "RUNNING"
        assert task.executor_run_id is None

    def test_update_state_cause(self, client, system_headers, task, project):
        response = self.patch(client, system_headers, project, task.id, {"status": "FAILED", "state_cause": "why"})
        assert response.status_code == 200
        assert response.json()["state_cause"] == "why"
        assert Task.query.get(task.id).state_cause == "why"

    @pytest.mark.parametrize("body", [
        {},
        {"state_cause": 1},
        {"status": "scheduled"},
        {"status": "running"},
        {"name": "other"},
        {"executor_run_id": 1},
        {"exit_code": "1"},
        {"exit_code": True},
        {"started_at": "not-a-date"},
        {"completed_at": 1},
    ])
    def test_invalid_body_fails(self, client, system_headers, task, body, project):
        response = self.patch(client, system_headers, project, task.id, body)
        assert response.status_code == 400
        assert Task.query.get(task.id).status == "PENDING"

    def test_not_found(self, client, system_headers, project):
        response = self.patch(client, system_headers, project, 999, {"status": "RUNNING"})
        assert response.status_code == 404

    def test_requires_auth(self, client, task, project):
        response = self.patch(client, {"Content-Type": "application/json"}, project, task.id, {"status": "RUNNING"})
        assert response.status_code == 401

    def test_forbidden(self, client, post_json_user_header, task, mock_kc_client, project):
        is_token_valid = mock_kc_client["wrappers_kc"].return_value.is_token_valid
        is_token_valid.side_effect = None
        is_token_valid.return_value = False
        response = self.patch(client, post_json_user_header, project, task.id, {"status": "RUNNING"})
        assert response.status_code == 403
        assert Task.query.get(task.id).status == "PENDING"
