import pytest

from app.models.task import Task


@pytest.fixture
def forbidden(mock_kc_client):
    is_token_valid = mock_kc_client["wrappers_kc"].return_value.is_token_valid
    is_token_valid.side_effect = None
    is_token_valid.return_value = False


class TestGetTasks:
    def ids(self, response):
        return [t["id"] for t in response.json["tasks"]]

    def test_list(self, make_task, client, simple_admin_header, project):
        first, second = make_task(project=project), make_task(project=project)
        response = client.get("/tasks", headers=simple_admin_header)
        assert response.status_code == 200
        assert self.ids(response) == [first.id, second.id]

    def test_filter_status(self, make_task, client, simple_admin_header, project):
        pending = make_task(project=project)
        make_task(project=project, status="RUNNING")
        response = client.get("/tasks?status=PENDING", headers=simple_admin_header)
        assert response.status_code == 200
        assert self.ids(response) == [pending.id]
        assert response.json["tasks"][0]["status"] == "PENDING"

    def test_filter_invalid_status(self, client, simple_admin_header):
        response = client.get("/tasks?status=queued", headers=simple_admin_header)
        assert response.status_code == 400

    def test_filter_project_id(self, make_task, client, simple_admin_header, project, other_project):
        make_task(project=project)
        other = make_task(project=other_project)
        response = client.get(f"/tasks?project_id={other_project.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert self.ids(response) == [other.id]

    def test_filters_combine(self, make_task, client, simple_admin_header, project, other_project):
        wanted = make_task(project=project)
        make_task(project=project, status="RUNNING")
        make_task(project=other_project)
        response = client.get(
            f"/tasks?status=PENDING&project_id={project.id}", headers=simple_admin_header
        )
        assert self.ids(response) == [wanted.id]

    def test_paginated(self, make_task, client, simple_admin_header, project):
        make_task(project=project)
        second = make_task(project=project)
        response = client.get("/tasks?page=2&per_page=1", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json["total"] == 2
        assert response.json["pages"] == 2
        assert response.json["page"] == 2
        assert response.json["per_page"] == 1
        assert self.ids(response) == [second.id]

    def test_requires_auth(self, client):
        assert client.get("/tasks").status_code == 401

    def test_forbidden(self, client, simple_user_header, forbidden):
        assert client.get("/tasks", headers=simple_user_header).status_code == 403


class TestRetryTask:
    @pytest.mark.parametrize("status", ["FAILED", "CANCELED"])
    def test_retry(self, make_task, client, simple_admin_header, project, status):
        task = make_task(
            project, status=status, dagster_run_id="run-1", exit_code=1,
            started_at="2026-01-01 10:00:00", completed_at="2026-01-01 10:30:00",
        )
        response = client.post(f"/tasks/{task.id}/retry", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json["status"] == "PENDING"
        assert response.json["attempt"] == 2
        for field in ("dagster_run_id", "exit_code", "started_at", "completed_at"):
            assert response.json[field] is None
        task = Task.query.get(task.id)
        assert task.status == "PENDING"
        assert task.attempt == 2
        assert task.dagster_run_id is None
        assert task.exit_code is None
        assert task.started_at is None
        assert task.completed_at is None

    def test_attempt_counts_up(self, make_task, client, simple_admin_header, project):
        task = make_task(project=project, status="FAILED")
        client.post(f"/tasks/{task.id}/retry", headers=simple_admin_header)
        Task.query.get(task.id).status = "FAILED"
        response = client.post(f"/tasks/{task.id}/retry", headers=simple_admin_header)
        assert response.json["attempt"] == 3

    @pytest.mark.parametrize("status", ["PENDING", "QUEUED", "RUNNING", "SUCCESS"])
    def test_other_states_fail(self, make_task, client, simple_admin_header, project, status):
        task = make_task(project=project, status=status, dagster_run_id="run-1")
        response = client.post(f"/tasks/{task.id}/retry", headers=simple_admin_header)
        assert response.status_code == 400
        task = Task.query.get(task.id)
        assert task.status == status
        assert task.attempt == 1
        assert task.dagster_run_id == "run-1"

    def test_not_found(self, client, simple_admin_header):
        assert client.post("/tasks/999/retry", headers=simple_admin_header).status_code == 404

    def test_requires_auth(self, make_task, client, project):
        task = make_task(project=project, status="FAILED")
        assert client.post(f"/tasks/{task.id}/retry").status_code == 401

    def test_forbidden(self, make_task, client, simple_user_header, project, forbidden):
        task = make_task(project=project, status="FAILED")
        response = client.post(f"/tasks/{task.id}/retry", headers=simple_user_header)
        assert response.status_code == 403
        assert Task.query.get(task.id).attempt == 1
