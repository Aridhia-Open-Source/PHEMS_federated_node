import json
import pytest

from app.models.task import Task


@pytest.fixture
def task(client, project, dataset):
    task = Task(name="task", docker_image="img:1", requested_by="user", dataset=dataset, project_id=project.id)
    task.add()
    return task


class TestPatchTask:
    def patch(self, client, headers, task_id, body):
        return client.patch(f"/tasks/{task_id}", data=json.dumps(body), headers=headers)

    def test_update_all_fields(self, client, post_json_admin_header, task):
        response = self.patch(client, post_json_admin_header, task.id, {
            "status": "FAILURE", "dagster_run_id": "run-1", "exit_code": 2,
            "started_at": "2026-01-01T10:00:00Z", "completed_at": "2026-01-01T10:30:00",
        })
        assert response.status_code == 200
        assert response.json["status"] == "FAILURE"
        task = Task.query.get(task.id)
        assert task.status == "FAILURE"
        assert task.dagster_run_id == "run-1"
        assert task.exit_code == 2
        assert task.started_at.isoformat() == "2026-01-01T10:00:00"
        assert task.completed_at.isoformat() == "2026-01-01T10:30:00"

    def test_update_status_only(self, client, post_json_admin_header, task):
        response = self.patch(client, post_json_admin_header, task.id, {"status": "RUNNING"})
        assert response.status_code == 200
        task = Task.query.get(task.id)
        assert task.status == "RUNNING"
        assert task.dagster_run_id is None

    @pytest.mark.parametrize("body", [
        {},
        {"status": "scheduled"},
        {"status": "running"},
        {"name": "other"},
        {"dagster_run_id": 1},
        {"exit_code": "1"},
        {"exit_code": True},
        {"started_at": "not-a-date"},
        {"completed_at": 1},
    ])
    def test_invalid_body_fails(self, client, post_json_admin_header, task, body):
        response = self.patch(client, post_json_admin_header, task.id, body)
        assert response.status_code == 400
        assert Task.query.get(task.id).status == "PENDING"

    def test_not_found(self, client, post_json_admin_header):
        response = self.patch(client, post_json_admin_header, 999, {"status": "RUNNING"})
        assert response.status_code == 404

    def test_requires_auth(self, client, task):
        response = self.patch(client, {"Content-Type": "application/json"}, task.id, {"status": "RUNNING"})
        assert response.status_code == 401

    def test_forbidden(self, client, post_json_user_header, task, mock_kc_client):
        is_token_valid = mock_kc_client["wrappers_kc"].return_value.is_token_valid
        is_token_valid.side_effect = None
        is_token_valid.return_value = False
        response = self.patch(client, post_json_user_header, task.id, {"status": "RUNNING"})
        assert response.status_code == 403
        assert Task.query.get(task.id).status == "PENDING"
