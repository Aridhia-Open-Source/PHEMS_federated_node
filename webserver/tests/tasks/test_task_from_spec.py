import pytest

from app.dtos.task import NewTaskDTO
from app.dtos.task_spec import TaskSpec
from app.helpers.exceptions import InvalidRequest
from app.models.api_request import ApiRequest
from app.models.dataset import Dataset
from app.models.pull_request import PullRequest
from app.models.task import Task
from app.models.trigger_state import TriggerState
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *

SPEC = {"name": "TestTask", "image": "img:1", "env": {"K": "v"}, "params": {"p": 1}}


@pytest.fixture
def api_request(client, project, dataset):
    api_request = ApiRequest(project_id=project.id, user_id="api-user", payload={"raw": True})
    api_request.add()
    return api_request


@pytest.fixture
def pull_request(client, project, dataset, default_repo):
    pull_request = PullRequest(
        project_id=project.id, trigger_repository_id=default_repo.id, number=7, title="PR title",
        raised_by="pr-user", merged_at="2026-01-01T10:00:00", merge_commit_sha="a" * 40,
        payload={"image": "img:1"},
    )
    pull_request.add()
    return pull_request


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


class TestNewTaskDTOFromSpec:
    def test_api_task_derived_from_spec(self, api_request, dataset):
        task = NewTaskDTO.from_spec(TaskSpec(**SPEC), api_request)
        assert task.name == "TestTask"
        assert task.docker_image == "img:1"
        assert task.params == {"p": 1}
        assert task.spec == TaskSpec(**SPEC).model_dump()
        assert task.dataset_id == dataset.id
        assert task.project_id == api_request.project_id
        assert task.requested_by == "api-user"
        assert task.trigger_id == api_request.id

    def test_pr_task_derived_from_spec(self, pull_request):
        task = NewTaskDTO.from_spec(TaskSpec(image="img:1"), pull_request)
        assert task.name == "PR title"
        assert task.requested_by == "pr-user"
        assert task.trigger_id == pull_request.id

    def test_dataset_override_in_same_project(self, api_request, second_dataset):
        task = NewTaskDTO.from_spec(TaskSpec(**SPEC, dataset=second_dataset.name), api_request)
        assert task.dataset_id == second_dataset.id

    def test_dataset_name_is_matched_exactly_within_the_project(self, api_request, second_dataset):
        spec = TaskSpec(**SPEC, dataset=second_dataset.name.upper())
        assert NewTaskDTO.from_spec(spec, api_request).dataset_id == second_dataset.id
        spec = TaskSpec(**SPEC, dataset=second_dataset.name[:-1])
        with pytest.raises(InvalidRequest, match="does not belong to project"):
            NewTaskDTO.from_spec(spec, api_request)

    def test_dataset_override_in_other_project_fails(self, api_request, other_project_dataset):
        with pytest.raises(InvalidRequest, match="does not belong to project"):
            NewTaskDTO.from_spec(TaskSpec(**SPEC, dataset=other_project_dataset.name), api_request)

    def test_no_dataset_and_no_default_is_allowed(self, api_request, project):
        project.default_dataset_id = None
        project.default_dataset = None
        assert NewTaskDTO.from_spec(TaskSpec(**SPEC), api_request).dataset_id is None


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
        api_request = ApiRequest.query.one()
        assert response.json["id"] == task.id
        assert response.json["api_request_id"] == api_request.id
        assert task.trigger_id == api_request.id
        assert task.attempt == 1
        assert task.status == "PENDING"
        assert api_request.state == TriggerState.YIELDED.value
        assert api_request.state_cause is None
        assert task.dataset is dataset
        assert task.name == "TestTask"
        assert task.docker_image == task_body["executors"][0]["image"]
        # The spec is stored once, normalised; the API request keeps the raw body
        assert task.spec["image"] == task_body["executors"][0]["image"]
        assert task.spec["env"] == task_body["executors"][0]["env"]
        assert task.spec["dataset"] == dataset.name
        assert "executors" not in task.spec
        assert api_request.payload["executors"] == task_body["executors"]
        assert api_request.payload["name"] == "Test Task"

    def test_invalid_spec_keeps_a_rejected_request(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project
        ):
        task_body["resources"] = {"limits": {"cpu": "abc"}}
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert Task.query.count() == 0
        api_request = ApiRequest.query.one()
        assert api_request.state == TriggerState.REJECTED.value
        assert api_request.state_cause == response.json["error"]
        assert api_request.payload["resources"] == {"limits": {"cpu": "abc"}}

    def test_dataset_of_another_project_keeps_a_rejected_request(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project,
            other_project
        ):
        # The body's project owns the dataset, the header's project does not
        response = self.post(client, post_json_admin_header, other_project, task_body)
        assert response.status_code == 400, response.json
        assert "does not belong to project" in response.json["error"]
        assert Task.query.count() == 0
        api_request = ApiRequest.query.one()
        assert api_request.state == TriggerState.REJECTED.value
        assert "does not belong to project" in api_request.state_cause
        assert api_request.project_id == other_project.id

    @pytest.mark.parametrize("executors", ["missing", []])
    def test_no_executors_fails(self, client, post_json_admin_header, task_body, project, executors):
        if executors == "missing":
            task_body.pop("executors")
        else:
            task_body["executors"] = executors
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert response.json["error"] == "executors must be a non-empty list of objects"
        assert Task.query.count() == 0
        assert ApiRequest.query.one().state == TriggerState.REJECTED.value

    def test_unknown_project_records_nothing(
            self, client, cr_client, registry_client, post_json_admin_header, task_body
        ):
        response = client.post(
            '/tasks', json=task_body, headers={**post_json_admin_header, "project-name": "NoSuchProject"}
        )
        assert response.status_code in (403, 404)
        assert ApiRequest.query.count() == 0
        assert Task.query.count() == 0

    def test_unauthenticated_records_nothing(self, client, task_body, project):
        response = client.post('/tasks', json=task_body, headers={"project-name": project.name})
        assert response.status_code == 401
        assert ApiRequest.query.count() == 0
