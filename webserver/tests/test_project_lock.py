import json
from http import HTTPStatus
from types import SimpleNamespace

import pytest

from app.models.dataset import Dataset
from app.models.project import Project
from app.models.pull_request_result import PullRequestResult
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.task_status import TaskStatus


@pytest.fixture
def audited(mock_kc_client, admin_user_uuid):
    """Writes are audited, which looks the caller up in Keycloak."""
    mock_kc_client["wrappers_kc"].return_value.get_user_by_email.return_value["id"] = admin_user_uuid


@pytest.fixture
def results_repo(client, project, secret):
    repo = ResultsRepository(
        uri="github.com/org/results", provider="github", api_uri="https://api.github.com",
        secret_id=secret.id, target_dir="results", project_id=project.id
    )
    repo.add()
    return repo


@pytest.fixture
def spare_secret(client, project):
    """A secret no repository or dataset uses, so it can be deleted."""
    secret = Secret(project_id=project.id, label="spare-creds", provider=SecretProviderType.K8S)
    secret.add()
    return secret


@pytest.fixture
def ids(client, k8s_client, audited, project, secret, spare_secret, default_repo, results_repo):
    dataset = Dataset.query.filter_by(project_id=project.id).one()
    return SimpleNamespace(
        project=project.id, trigger_repo=default_repo.id, results_repo=results_repo.id,
        dataset=dataset.id, secret=secret.label, spare_secret=spare_secret.label,
    )


# Each is a change the lock guards: the request that makes it, with the headers of an admin
GUARDED = {
    "patch_project": lambda c, h, i: c.patch(f"/projects/{i.project}", json={"enabled": True}, headers=h),
    "delete_project": lambda c, h, i: c.delete(f"/projects/{i.project}", headers=h),
    "patch_trigger_repo": lambda c, h, i: c.patch(
        f"/trigger_repositories/{i.trigger_repo}", json={"base_branch": "dev"}, headers=h
    ),
    "delete_trigger_repo": lambda c, h, i: c.delete(f"/trigger_repositories/{i.trigger_repo}", headers=h),
    "patch_results_repo": lambda c, h, i: c.patch(
        f"/results_repositories/{i.results_repo}", json={"target_dir": "out"}, headers=h
    ),
    "delete_results_repo": lambda c, h, i: c.delete(f"/results_repositories/{i.results_repo}", headers=h),
    "patch_dataset": lambda c, h, i: c.patch(f"/datasets/{i.dataset}", json={"host": "other.example.com"}, headers=h),
    "delete_dataset": lambda c, h, i: c.delete(f"/datasets/{i.dataset}", headers=h),
    "delete_secret": lambda c, h, i: c.delete(f"/projects/{i.project}/secrets/{i.spare_secret}", headers=h),
}
SUCCESS_CODES = {
    "patch_project": HTTPStatus.OK, "delete_project": HTTPStatus.NO_CONTENT,
    "patch_trigger_repo": HTTPStatus.OK, "delete_trigger_repo": HTTPStatus.NO_CONTENT,
    "patch_results_repo": HTTPStatus.OK, "delete_results_repo": HTTPStatus.NO_CONTENT,
    "patch_dataset": HTTPStatus.ACCEPTED, "delete_dataset": HTTPStatus.NO_CONTENT,
    "delete_secret": HTTPStatus.NO_CONTENT,
}


def lock(project: Project, locked=True):
    project.locked = locked
    project.add()


def make_result(make_task, results_repo, task_status, state):
    task = make_task(status=task_status)
    PullRequestResult(task_id=task.id, results_repository_id=results_repo.id, state=state).add()
    return task


class TestLockFlag:
    def patch(self, client, headers, project, body):
        return client.patch(f"/projects/{project.id}", json=body, headers=headers)

    def test_a_project_starts_unlocked(self, client, simple_admin_header, project):
        response = client.get(f"/projects/{project.id}", headers=simple_admin_header)
        assert response.json["locked"] is False

    def test_lock_and_unlock(self, client, post_json_admin_header, project):
        response = self.patch(client, post_json_admin_header, project, {"locked": True})
        assert response.status_code == HTTPStatus.OK
        assert response.json["locked"] is True
        assert Project.query.one().locked is True

        response = self.patch(client, post_json_admin_header, project, {"locked": False})
        assert response.status_code == HTTPStatus.OK
        assert response.json["locked"] is False
        assert Project.query.one().locked is False

    def test_locking_leaves_enabled_alone(self, client, post_json_admin_header, project):
        project.enabled = True
        project.add()
        assert self.patch(client, post_json_admin_header, project, {"locked": True}).json["enabled"] is True

    def test_unlock_with_tasks_in_flight(self, client, post_json_admin_header, project, make_task):
        make_task(status=TaskStatus.RUNNING.value)
        lock(project)
        response = self.patch(client, post_json_admin_header, project, {"locked": False})
        assert response.status_code == HTTPStatus.OK
        assert response.json["locked"] is False

    @pytest.mark.parametrize("body", [{"locked": "yes"}, {"locked": None}, {"locked": 1}, {}, {"name": "x"}])
    def test_invalid_body(self, client, post_json_admin_header, project, body):
        assert self.patch(client, post_json_admin_header, project, body).status_code == HTTPStatus.BAD_REQUEST
        assert Project.query.one().locked is False


class TestInFlight:
    @pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING])
    def test_unfinished_tasks(self, project, make_task, status):
        task = make_task(status=status.value)
        assert project.in_flight_task_ids() == [task.id]

    def test_a_succeeded_task_without_a_result(self, project, make_task):
        task = make_task(status=TaskStatus.SUCCESS.value)
        assert project.in_flight_task_ids() == [task.id]

    def test_a_result_in_progress(self, project, make_task, results_repo):
        task = make_result(make_task, results_repo, TaskStatus.SUCCESS.value, "IN_PROGRESS")
        assert project.in_flight_task_ids() == [task.id]

    @pytest.mark.parametrize("state", ["DELIVERED", "FAILED"])
    def test_a_result_that_is_done(self, project, make_task, results_repo, state):
        make_result(make_task, results_repo, TaskStatus.SUCCESS.value, state)
        assert project.in_flight_task_ids() == []

    @pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.CANCELED])
    def test_a_task_that_ended_without_success(self, project, make_task, status):
        make_task(status=status.value)
        assert project.in_flight_task_ids() == []

    def test_only_this_projects_tasks(self, project, other_project, make_task):
        make_task(project=other_project, status=TaskStatus.RUNNING.value)
        assert project.in_flight_task_ids() == []

    def test_the_ids_are_listed_in_order(self, project, make_task):
        tasks = [make_task(status=TaskStatus.PENDING.value) for _ in range(3)]
        assert project.in_flight_task_ids() == [t.id for t in tasks]


@pytest.mark.parametrize("change", GUARDED)
class TestChangeNeedsLockedAndDrained:
    def test_refused_while_unlocked(self, client, post_json_admin_header, ids, project, change):
        response = GUARDED[change](client, post_json_admin_header, ids)
        assert response.status_code == HTTPStatus.CONFLICT
        assert "must be locked" in response.json["error"]
        assert Project.query.one().id == project.id

    @pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING])
    def test_refused_with_a_task_in_flight(
        self, client, post_json_admin_header, ids, project, make_task, change, status
    ):
        lock(project)
        task = make_task(status=status.value)
        response = GUARDED[change](client, post_json_admin_header, ids)
        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json["details"] == [task.id]

    def test_refused_with_a_success_that_has_no_result(
        self, client, post_json_admin_header, ids, project, make_task, change
    ):
        lock(project)
        task = make_task(status=TaskStatus.SUCCESS.value)
        response = GUARDED[change](client, post_json_admin_header, ids)
        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json["details"] == [task.id]

    def test_refused_with_a_result_in_progress(
        self, client, post_json_admin_header, ids, project, make_task, results_repo, change
    ):
        lock(project)
        task = make_result(make_task, results_repo, TaskStatus.SUCCESS.value, "IN_PROGRESS")
        response = GUARDED[change](client, post_json_admin_header, ids)
        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json["details"] == [task.id]

    def test_allowed_when_locked_and_drained(self, client, post_json_admin_header, ids, project, change):
        lock(project)
        response = GUARDED[change](client, post_json_admin_header, ids)
        assert response.status_code == SUCCESS_CODES[change], response.json

    def test_allowed_once_the_work_has_drained(
        self, client, post_json_admin_header, ids, project, make_task, results_repo, change
    ):
        lock(project)
        running = make_task(status=TaskStatus.RUNNING.value)
        delivering = make_result(make_task, results_repo, TaskStatus.SUCCESS.value, "IN_PROGRESS")
        assert GUARDED[change](client, post_json_admin_header, ids).status_code == HTTPStatus.CONFLICT

        running.status = TaskStatus.FAILED.value
        running.add()
        result = PullRequestResult.query.filter_by(task_id=delivering.id).one()
        result.state = "DELIVERED"
        result.add()
        response = GUARDED[change](client, post_json_admin_header, ids)
        assert response.status_code == SUCCESS_CODES[change], response.json


class TestChangeNeedsTheLockOfTheProjectItMovesTo:
    @pytest.mark.parametrize("path", ["trigger_repositories", "results_repositories"])
    def test_moving_a_repository_into_a_project_in_flight(
        self, client, post_json_admin_header, ids, project, other_project, make_task, path
    ):
        lock(project)
        lock(other_project)
        make_task(project=other_project, status=TaskStatus.RUNNING.value)
        repo_id = ids.trigger_repo if path == "trigger_repositories" else ids.results_repo
        response = client.patch(f"/{path}/{repo_id}", json={"project_id": other_project.id}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.CONFLICT


class TestCredentialRotationIsExempt:
    @pytest.fixture
    def busy(self, project, make_task):
        """Locked, with a task in flight."""
        lock(project)
        make_task(status=TaskStatus.RUNNING.value)

    def test_secret_values(self, client, post_json_admin_header, ids, busy):
        response = client.patch(
            f"/projects/{ids.project}/secrets/{ids.secret}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}), headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.OK

    def test_secret_values_while_unlocked(self, client, post_json_admin_header, ids):
        response = client.patch(
            f"/projects/{ids.project}/secrets/{ids.secret}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}), headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("path, key", [("trigger_repositories", "trigger_repo"), ("results_repositories", "results_repo")])
    def test_a_repository_secret_label(self, client, post_json_admin_header, ids, busy, path, key):
        response = client.patch(
            f"/{path}/{getattr(ids, key)}", json={"secret_label": ids.spare_secret}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.OK
        assert Secret.query.filter_by(label=ids.spare_secret).one().id == response.json["secret_id"]

    @pytest.mark.parametrize("path, key", [("trigger_repositories", "trigger_repo"), ("results_repositories", "results_repo")])
    def test_the_api_uri_stays_locked(self, client, post_json_admin_header, ids, busy, path, key):
        response = client.patch(
            f"/{path}/{getattr(ids, key)}", json={"api_uri": "https://git.example.com/api"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CONFLICT

    @pytest.mark.parametrize("path, key", [("trigger_repositories", "trigger_repo"), ("results_repositories", "results_repo")])
    def test_the_secret_label_with_another_field_stays_locked(
        self, client, post_json_admin_header, ids, busy, path, key
    ):
        response = client.patch(
            f"/{path}/{getattr(ids, key)}", json={"secret_label": ids.spare_secret, "provider": "gitea"},
            headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CONFLICT


class TestCreatingChildren:
    def test_a_trigger_repository_is_allowed_while_in_flight(
        self, client, post_json_admin_header, project, secret, make_task
    ):
        lock(project)
        make_task(status=TaskStatus.RUNNING.value)
        response = client.post("/trigger_repositories", json={
            "uri": "github.com/org/new", "provider": "github", "secret_label": secret.label,
            "project_id": project.id,
        }, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.CREATED, response.json

    def test_a_secret_is_allowed_while_in_flight(
        self, client, k8s_client, audited, post_json_admin_header, project, make_task
    ):
        lock(project)
        make_task(status=TaskStatus.RUNNING.value)
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"provider": "K8S", "label": "new-creds", "values": {"TOKEN": "t"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED, response.json

    @pytest.fixture
    def results_post_body(self, project, secret):
        return {
            "uri": "github.com/org/results", "provider": "github", "api_uri": "https://api.github.com",
            "secret_label": secret.label, "target_dir": "results", "project_id": project.id,
        }

    def test_a_results_repository_is_refused_while_unlocked(
        self, client, post_json_admin_header, project, results_post_body
    ):
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.CONFLICT
        assert ResultsRepository.query.count() == 0

    def test_a_results_repository_is_refused_with_a_task_in_flight(
        self, client, post_json_admin_header, project, results_post_body, make_task
    ):
        lock(project)
        task = make_task(status=TaskStatus.PENDING.value)
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json["details"] == [task.id]
        assert ResultsRepository.query.count() == 0

    def test_a_results_repository_is_allowed_when_locked_and_drained(
        self, client, post_json_admin_header, project, results_post_body
    ):
        lock(project)
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.CREATED, response.json
        assert ResultsRepository.query.count() == 1
