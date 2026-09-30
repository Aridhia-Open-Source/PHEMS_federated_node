import pytest
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.helpers.exceptions import InvalidDBEntry, InvalidRequest
from app.models.api_request import ApiRequest
from app.models.dataset import Dataset
from app.models.pull_request import PullRequest
from app.models.task import Task
from app.models.task_request import TaskRequest
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *

SPEC = {
    "name": "TestTask", "description": None, "image": "img:1", "command": None, "env": {"K": "v"},
    "params": {"p": 1}, "dataset": None, "tags": {}, "resources": {}, "repository": None,
}


@pytest.fixture
def api_task_request(client, project, dataset):
    api_request = ApiRequest(project_id=project.id, user_id="user", payload={"raw": True})
    api_request.add()
    task_request = TaskRequest(api_request_id=api_request.id, project_id=project.id, payload=dict(SPEC))
    task_request.add()
    return task_request


@pytest.fixture
def pr_task_request(client, project, dataset, default_repo):
    pull_request = PullRequest(
        trigger_repository_id=default_repo.id, number=7, title="PR title", raised_by="user",
        merged_at="2026-01-01T10:00:00", merge_commit_sha="a" * 40, payload={"image": "img:1"},
    )
    pull_request.add()
    task_request = TaskRequest(
        pull_request_id=pull_request.id, project_id=project.id, payload={**SPEC, "name": None}
    )
    task_request.add()
    return task_request


@pytest.fixture
def second_dataset(client, user_uuid, project, k8s_secret):
    ds = Dataset(name="SecondDs", host="example.com", k8s_secret_name=k8s_secret.name, project_id=project.id)
    ds.add(user_id=user_uuid)
    return ds


@pytest.fixture
def other_project_dataset(client, user_uuid, other_project, k8s_secret):
    ds = Dataset(name="OtherDs", host="example.com", k8s_secret_name=k8s_secret.name, project_id=other_project.id)
    ds.add(user_id=user_uuid)
    return ds


class TestTaskFromTaskRequest:
    def test_api_task_derived_from_spec(self, api_task_request, dataset):
        task = Task.from_task_request(api_task_request, requested_by="user")
        assert task.name == "TestTask"
        assert task.docker_image == "img:1"
        assert task.params == {"p": 1}
        assert task.dataset is dataset
        assert task.project_id == api_task_request.project_id
        assert task.requested_by == "user"
        assert task.task_request_id == api_task_request.id
        assert task.api_request_id == api_task_request.api_request_id
        assert task.pr_number is None

    def test_pr_task_derived_from_spec(self, pr_task_request, default_repo):
        task = Task.from_task_request(pr_task_request, requested_by="user")
        assert task.name == "PR title"
        assert task.pr_repository_id == default_repo.id
        assert task.pr_number == 7
        assert task.api_request_id is None

    def test_no_trigger_payload(self):
        assert "trigger_payload" not in Task.__table__.columns

    def test_dataset_override_in_same_project(self, api_task_request, second_dataset):
        api_task_request.payload = {**SPEC, "dataset": second_dataset.name}
        task = Task.from_task_request(api_task_request, requested_by="user")
        assert task.dataset is second_dataset

    def test_dataset_override_in_other_project_fails(self, api_task_request, other_project_dataset):
        api_task_request.payload = {**SPEC, "dataset": other_project_dataset.name}
        with pytest.raises(InvalidRequest, match="does not belong to project"):
            Task.from_task_request(api_task_request, requested_by="user")

    def test_no_dataset_and_no_default_fails(self, api_task_request, project):
        project.default_dataset_id = None
        with pytest.raises(InvalidRequest, match="has no default dataset"):
            Task.from_task_request(api_task_request, requested_by="user")


class TestTaskRequestSource:
    def test_both_sources_fails(self, project):
        with pytest.raises(InvalidDBEntry):
            TaskRequest(project_id=project.id, payload={}, pull_request_id=1, api_request_id=1)

    def test_no_source_fails(self, project):
        with pytest.raises(InvalidDBEntry):
            TaskRequest(project_id=project.id, payload={})

    def test_db_check_rejects_no_source(self, project):
        task_request = TaskRequest(project_id=project.id, payload={}, api_request_id=1)
        task_request.api_request_id = None
        db.session.add(task_request)
        with pytest.raises(IntegrityError, match="ck_task_requests_one_source"):
            db.session.flush()
        db.session.rollback()


class TestPostTasks:
    def post(self, client, headers, project, body):
        headers = {**headers, "project-name": project.name}
        return client.post('/tasks', json=body, headers=headers)

    def test_creates_request_and_task_once(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, dataset
        ):
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 201, response.json
        task = Task.query.one()
        task_request = TaskRequest.query.one()
        api_request = ApiRequest.query.one()
        assert task.task_request_id == task_request.id
        assert task.api_request_id == api_request.id
        assert task.dataset is dataset
        assert task.name == "TestTask"
        assert task.docker_image == task_body["executors"][0]["image"]
        # The spec is stored once, normalised; the API request keeps the raw body
        assert task_request.payload["image"] == task_body["executors"][0]["image"]
        assert task_request.payload["env"] == task_body["executors"][0]["env"]
        assert task_request.payload["dataset"] == dataset.name
        assert "executors" not in task_request.payload
        assert api_request.payload["executors"] == task_body["executors"]
        assert api_request.payload["name"] == "Test Task"

    def test_invalid_spec_creates_nothing(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project
        ):
        task_body["resources"] = {"limits": {"cpu": "abc"}}
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert Task.query.count() == 0
        assert TaskRequest.query.count() == 0

    def test_failed_task_creation_creates_nothing(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project,
            other_project
        ):
        # The body's project owns the dataset, the header's project does not
        response = self.post(client, post_json_admin_header, other_project, task_body)
        assert response.status_code == 400, response.json
        assert "does not belong to project" in response.json["error"]
        assert ApiRequest.query.count() == 0
        assert TaskRequest.query.count() == 0
        assert Task.query.count() == 0
