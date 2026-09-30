import pytest
from sqlalchemy.exc import IntegrityError

from app.dtos.task_result import TaskResultDTO
from app.models.results_repository import ResultsRepository
from app.models.task import Task
from app.models.task_result import TaskResult
from app.models.task_result_status import TaskResultStatus


@pytest.fixture
def task(client, project, dataset):
    task = Task(
        name="task", docker_image="registry/image:1.0", requested_by="user",
        dataset=dataset, project_id=project.id
    )
    task.add()
    return task


@pytest.fixture
def results_repo(client, project, k8s_secret):
    repo = ResultsRepository(
        uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
        k8s_secret_id=k8s_secret.id, target_dir="results", project_id=project.id
    )
    repo.add()
    return repo


@pytest.fixture
def task_result(task, results_repo):
    task_result = TaskResult(task_id=task.id, results_repository_id=results_repo.id)
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
        assert task_result.branch is None
        assert task_result.created_at is not None

    def test_unique_per_task_and_destination(self, task, results_repo, task_result):
        with pytest.raises(IntegrityError):
            TaskResult(task_id=task.id, results_repository_id=results_repo.id).add()

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
        assert response.json == [TaskResultDTO.from_model(task_result).dump()]
        assert response.json[0]["status"] == "PENDING"

    def test_list_unknown_task(self, client, simple_admin_header):
        response = client.get("/tasks/9999/results", headers=simple_admin_header)
        assert response.status_code == 404

    def test_get_by_id(self, client, simple_admin_header, task_result):
        response = client.get(f"/task_results/{task_result.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == TaskResultDTO.from_model(task_result).dump()

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/task_results/9999", headers=simple_admin_header)
        assert response.status_code == 404
