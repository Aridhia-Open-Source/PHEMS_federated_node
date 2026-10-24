import json

import pytest

from app.dtos.task import NewTaskDTO
from app.dtos.task_spec import TaskSpecRequest
from app.helpers.base_model import db
from app.helpers.const import SPEC_RAW_MAX_BYTES, TASK_NAME_MAX_LENGTH
from app.helpers.exceptions import InvalidRequest
from app.models.api_request_trigger import ApiRequestTrigger
from app.models.dataset import Dataset
from app.models.project_dataset import ProjectDataset
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.pull_request_trigger import PullRequestTrigger
from tests.helpers.pull_requests import add_pull_request_trigger
from app.models.task import Task
from app.models.task_spec import TaskSpec
from app.models.trigger_state import TriggerState
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *

SPEC = {"name": "TestTask", "image": "img:1", "env": {"K": "v"}, "params": {"p": 1}}


@pytest.fixture
def api_request(client, project, dataset):
    api_request = ApiRequestTrigger(project_id=project.id, user_id="api-user")
    api_request.add()
    return api_request


@pytest.fixture
def pull_request(client, project, dataset, default_repo):
    return add_pull_request_trigger(default_repo, 7, title="PR title", raised_by="pr-user")


@pytest.fixture
def second_dataset(client, user_uuid, project, secret):
    ds = Dataset(name="SecondDs", host="example.com", port=5432, secret_id=secret.id)
    ds.add(user_id=user_uuid)
    ProjectDataset(project.id, ds.id).add()
    return ds


@pytest.fixture
def other_project_dataset(client, user_uuid, other_project):
    secret = Secret(label="other-test-creds", provider=SecretProviderType.K8S)
    secret.add()
    ds = Dataset(name="OtherDs", host="example.com", port=5432, secret_id=secret.id)
    ds.add(user_id=user_uuid)
    ProjectDataset(other_project.id, ds.id).add()
    return ds


class TestNewTaskDTOFromSpec:
    def test_api_task_derived_from_spec(self, api_request, dataset):
        task = NewTaskDTO.from_spec(TaskSpecRequest(**SPEC), api_request)
        assert task.name == "TestTask"
        assert task.params == {"p": 1}
        assert task.spec == {"image": "img:1", "dataset_id": dataset.id, "env": {"K": "v"}}
        assert task.project_id == api_request.project_id
        assert task.requested_by == "api-user"
        assert task.trigger_id == api_request.id

    def test_pr_task_derived_from_spec(self, pull_request):
        task = NewTaskDTO.from_spec(TaskSpecRequest(image="img:1"), pull_request)
        assert task.name == "PR title"
        assert task.requested_by == "pr-user"
        assert task.trigger_id == pull_request.id

    def test_dataset_override_in_same_project(self, api_request, second_dataset):
        task = NewTaskDTO.from_spec(TaskSpecRequest(**SPEC, dataset=second_dataset.name), api_request)
        assert task.spec["dataset_id"] == second_dataset.id

    def test_dataset_name_is_matched_exactly_within_the_project(self, api_request, second_dataset):
        spec = TaskSpecRequest(**SPEC, dataset=second_dataset.name.upper())
        assert NewTaskDTO.from_spec(spec, api_request).spec["dataset_id"] == second_dataset.id
        spec = TaskSpecRequest(**SPEC, dataset=second_dataset.name[:-1])
        with pytest.raises(InvalidRequest, match="does not belong to project"):
            NewTaskDTO.from_spec(spec, api_request)

    def test_dataset_override_in_other_project_fails(self, api_request, other_project_dataset):
        with pytest.raises(InvalidRequest, match="does not belong to project"):
            NewTaskDTO.from_spec(TaskSpecRequest(**SPEC, dataset=other_project_dataset.name), api_request)

    def test_inactive_dataset_override_fails(self, api_request, second_dataset, project):
        assignment = ProjectDataset.query.filter_by(project_id=project.id, dataset_id=second_dataset.id).one()
        assignment.revoked = True
        db.session.commit()
        with pytest.raises(InvalidRequest, match="is not active in project"):
            NewTaskDTO.from_spec(TaskSpecRequest(**SPEC, dataset=second_dataset.name), api_request)

    def test_disabled_default_dataset_fails(self, api_request, dataset, project):
        assignment = ProjectDataset.query.filter_by(project_id=project.id, dataset_id=dataset.id).one()
        assignment.enabled = False
        db.session.commit()
        with pytest.raises(InvalidRequest, match="is not active in project"):
            NewTaskDTO.from_spec(TaskSpecRequest(**SPEC), api_request)

    def test_no_dataset_and_no_default_is_allowed(self, api_request, project):
        project.default_dataset_id = None
        assert NewTaskDTO.from_spec(TaskSpecRequest(**SPEC), api_request).spec["dataset_id"] is None


class TestPostTasks:
    def post(self, client, headers, project, body):
        return client.post(f'/projects/{project.id}/tasks', json=body, headers=headers)

    def test_creates_request_and_task_once(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, dataset
        ):
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 201, response.json()
        task = Task.query.one()
        api_request = ApiRequestTrigger.query.one()
        assert response.json()["id"] == task.id
        assert response.json()["api_request_id"] == api_request.id
        assert task.trigger_id == api_request.id
        assert task.attempt == 1
        assert task.status == "PENDING"
        assert api_request.state == TriggerState.YIELDED.value
        assert api_request.state_cause is None
        assert task.name == "TestTask"
        # The spec is its own row, normalised; the API request keeps the raw body
        spec = TaskSpec.query.one()
        assert task.spec is spec
        assert spec.image == task_body["executors"][0]["image"]
        assert spec.env == task_body["executors"][0]["env"]
        assert spec.dataset is dataset
        assert json.loads(api_request.spec_raw) == task_body
        assert response.json().keys().isdisjoint({"spec_raw", "payload"})

    def test_task_is_pinned_to_its_configuration(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, dataset
        ):
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 201, response.json()
        task = Task.query.one()
        assert task.config_snapshot["version"] == 1 and task.config_snapshot["results"] is None
        assert task.config_snapshot["dataset"]["name"] == dataset.name
        assert task.config_hash and len(task.config_hash) == 64

    def test_response_of_the_task_has_its_spec_and_not_the_raw_body(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, dataset
        ):
        created = self.post(client, post_json_admin_header, project, task_body)
        response = client.get(f"/projects/{project.id}/tasks/{created.json()['id']}", headers=post_json_admin_header)
        assert response.status_code == 200
        assert response.json()["spec"] == {
            "image": task_body["executors"][0]["image"], "dataset_id": dataset.id,
            "env": task_body["executors"][0]["env"],
        }
        assert "spec_raw" not in response.json()

    def test_a_task_without_a_dataset_is_created(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, other_project
        ):
        task_body["tags"].pop("dataset_id")
        task_body["project_id"] = other_project.id
        response = self.post(client, post_json_admin_header, other_project, task_body)
        assert response.status_code == 201, response.json()
        assert Task.query.one().spec.dataset_id is None

    @pytest.mark.parametrize("env", [{"1BAD": "x"}, {"CDM_SCHEMA": "x"}, {"WRITE_SCHEMA": "x"}])
    def test_invalid_env_keeps_a_rejected_request_with_the_raw_body(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, env
        ):
        task_body["executors"][0]["env"] = env
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert Task.query.count() == 0
        assert TaskSpec.query.count() == 0
        api_request = ApiRequestTrigger.query.one()
        assert api_request.state == TriggerState.REJECTED.value
        assert api_request.state_cause == response.json()["error"]
        assert json.loads(api_request.spec_raw) == task_body

    def test_body_over_the_cap_is_rejected_without_keeping_it(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project
        ):
        task_body["tags"]["padding"] = "x" * SPEC_RAW_MAX_BYTES
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert "limit" in response.json()["error"]
        api_request = ApiRequestTrigger.query.one()
        assert api_request.state == TriggerState.REJECTED.value
        assert api_request.spec_raw is None
        assert Task.query.count() == 0

    def test_a_disabled_project_rejects_the_task(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, disabled_project
        ):
        response = self.post(client, post_json_admin_header, disabled_project, task_body)
        assert response.status_code == 409
        assert response.json()["error"] == f"Project '{disabled_project.name}' is disabled"
        assert Task.query.count() == 0
        assert ApiRequestTrigger.query.count() == 0

    def test_a_revoked_project_rejects_the_task(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project
        ):
        project.revoked = True
        db.session.commit()
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 409
        assert response.json()["error"] == f"Project {project.id} is revoked"
        assert Task.query.count() == 0
        assert ApiRequestTrigger.query.count() == 0

    def test_a_disabled_and_revoked_project_is_refused_as_disabled(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, disabled_project
        ):
        disabled_project.revoked = True
        db.session.commit()
        response = self.post(client, post_json_admin_header, disabled_project, task_body)
        assert response.status_code == 409
        assert response.json()["error"] == f"Project '{disabled_project.name}' is disabled"

    def test_invalid_spec_keeps_a_rejected_request(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project
        ):
        task_body["resources"] = {"limits": {"cpu": "abc"}}
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert Task.query.count() == 0
        api_request = ApiRequestTrigger.query.one()
        assert api_request.state == TriggerState.REJECTED.value
        assert api_request.state_cause == response.json()["error"]
        assert json.loads(api_request.spec_raw)["resources"] == {"limits": {"cpu": "abc"}}

    def test_name_over_the_limit_keeps_a_rejected_request(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project
        ):
        task_body["name"] = "a" * (TASK_NAME_MAX_LENGTH + 1)
        response = self.post(client, post_json_admin_header, project, task_body)
        assert response.status_code == 400
        assert Task.query.count() == 0
        assert ApiRequestTrigger.query.one().state == TriggerState.REJECTED.value

    def test_dataset_of_another_project_keeps_a_rejected_request(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project,
            other_project
        ):
        # The body's project owns the dataset, the header's project does not
        response = self.post(client, post_json_admin_header, other_project, task_body)
        assert response.status_code == 400, response.json()
        assert "does not belong to project" in response.json()["error"]
        assert Task.query.count() == 0
        api_request = ApiRequestTrigger.query.one()
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
        assert response.json()["error"] == "executors must be a non-empty list of objects"
        assert Task.query.count() == 0
        assert ApiRequestTrigger.query.one().state == TriggerState.REJECTED.value

    def test_unknown_project_records_nothing(
            self, client, cr_client, registry_client, post_json_admin_header, task_body
        ):
        response = client.post('/projects/99999/tasks', json=task_body, headers=post_json_admin_header)
        assert response.status_code == 404
        assert ApiRequestTrigger.query.count() == 0
        assert Task.query.count() == 0

    def test_unauthenticated_records_nothing(self, client, task_body, project):
        response = client.post(f'/projects/{project.id}/tasks', json=task_body)
        assert response.status_code == 401
        assert ApiRequestTrigger.query.count() == 0
