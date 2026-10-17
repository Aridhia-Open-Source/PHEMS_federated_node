from unittest.mock import MagicMock

import pytest

from app.backend import BackendAPI
from app.models import (
    Dataset, ProjectDataset, ProjectTriggerRepository, PullRequestResultStep, PullRequestTrigger, TriggerRepository,
)
from app.tests.conftest import SAMPLE_SECRET, SAMPLE_DATASET, SAMPLE_PR, SAMPLE_REPOSITORY_OBJ, SAMPLE_TRIGGER_REPOSITORY, make_response





@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def api(session):
    return BackendAPI(session=session, logger=MagicMock())


class TestLogin:
    def test_refresh_token_is_preferred(self, api, session):
        session.post.return_value = make_response({"refresh_token": "r", "token": "t"})

        api.login("user", "pass")

        assert session.adapter.access_token == "r"

    def test_falls_back_to_the_access_token(self, api, session):
        session.post.return_value = make_response({"token": "t"})

        api.login("user", "pass")

        assert session.adapter.access_token == "t"

    def test_credentials_are_form_encoded(self, api, session):
        session.post.return_value = make_response({"token": "t"})

        api.login("user", "pass")

        assert session.post.call_args.args[0] == "/login"
        assert session.post.call_args.kwargs["data"] == {
            "username": "user", "password": "pass",
        }


class TestRepositories:
    def test_get_repositories(self, api, session):
        session.get.return_value = make_response([SAMPLE_REPOSITORY_OBJ])

        repos = api.get_project_trigger_repositories(4)

        assert [type(r) for r in repos] == [ProjectTriggerRepository]
        assert repos[0].repo_path == "org/repo"

    def test_get_active_repositories(self, api, session):
        session.get.return_value = make_response([SAMPLE_REPOSITORY_OBJ])

        api.get_project_trigger_repositories(4, active=True)

        session.get.assert_called_once_with("/projects/4/repositories/triggers", params={"active": "true"})

    def test_get_all_repositories_sends_no_filter(self, api, session):
        session.get.return_value = make_response([SAMPLE_REPOSITORY_OBJ])

        api.get_project_trigger_repositories(4)

        session.get.assert_called_once_with("/projects/4/repositories/triggers", params=None)

    def test_get_repository(self, api, session):
        session.get.return_value = make_response(SAMPLE_REPOSITORY_OBJ)

        assert api.get_project_trigger_repository(4, 1).trigger_repository.id == 1
        session.get.assert_called_once_with("/projects/4/repositories/triggers/1")

    def test_patch_repository(self, api, session):
        session.patch.return_value = make_response(SAMPLE_REPOSITORY_OBJ)

        api.patch_project_trigger_repository(4, 1, {"base_branch": "dev"})

        assert session.patch.call_args.args[0] == "/projects/4/repositories/triggers/1"
        assert session.patch.call_args.kwargs["json"] == {"base_branch": "dev"}

    def test_create_repository_is_global(self, api, session):
        session.post.return_value = make_response(SAMPLE_TRIGGER_REPOSITORY)

        repo = api.create_repository("github.com/org/repo", "github", "https://api.github.com", "creds")

        assert type(repo) is TriggerRepository
        assert session.post.call_args.args == ("/global/repositories/triggers",)
        assert set(session.post.call_args.kwargs["json"]) == {"uri", "provider", "api_uri", "secret_label"}

    def test_assign_repository_puts_under_the_project(self, api, session):
        session.put.return_value = make_response(SAMPLE_REPOSITORY_OBJ)

        assignment = api.assign_repository(4, 1, "specs", "main")

        assert type(assignment) is ProjectTriggerRepository
        assert session.put.call_args.args == ("/projects/4/repositories/triggers/1",)
        assert session.put.call_args.kwargs["json"] == {"watch_dir": "specs", "base_branch": "main"}

    def test_delete_repository(self, api, session):
        api.delete_repository(3)

        session.delete.assert_called_once_with("/global/repositories/triggers/3")


class TestPullRequests:
    def _page(self, prs, total):
        return make_response({"items": prs, "total": total})

    def test_single_page(self, api, session):
        session.get.return_value = self._page([SAMPLE_PR], 1)

        prs = api.get_pull_requests(project_id=1, repository_id=1, state="UNKNOWN")

        assert [type(p) for p in prs] == [PullRequestTrigger]
        assert session.get.call_count == 1

    def test_pagination_follows_the_total(self, api, session):
        second = {**SAMPLE_PR, "number": 6}
        session.get.side_effect = [self._page([SAMPLE_PR], 2), self._page([second], 2)]

        prs = api.get_pull_requests(project_id=1, repository_id=1, state="UNKNOWN")

        assert [p.number for p in prs] == [5, 6]
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_pagination_stops_on_an_empty_page(self, api, session):
        session.get.side_effect = [self._page([SAMPLE_PR], 99), self._page([], 99)]

        assert len(api.get_pull_requests(project_id=1, repository_id=1, state="UNKNOWN")) == 1

    def test_the_state_is_sent_as_a_query_param(self, api, session):
        session.get.return_value = self._page([], 0)

        api.get_pull_requests(project_id=1, repository_id=1, state="UNKNOWN")

        assert session.get.call_args.kwargs["params"]["state"] == "UNKNOWN"

    def test_the_task_id_is_sent_as_a_query_param(self, api, session):
        session.get.return_value = self._page([SAMPLE_PR], 1)

        api.get_pull_requests(project_id=1, repository_id=1, task_id=9)

        assert session.get.call_args.kwargs["params"] == {"task_id": 9, "page": 1, "per_page": 100}

    def test_batch_creation(self, api, session):
        session.post.return_value = make_response({"created": [1], "existing": [2]})

        result = api.create_pull_requests_batch(3, [{"number": 1}, {"number": 2}])

        assert session.post.call_args.args[0] == "/global/repositories/triggers/3/pull_requests"
        assert session.post.call_args.kwargs["json"] == {"pull_requests": [{"number": 1}, {"number": 2}]}
        assert result == {"created": [1], "existing": [2]}

    def test_batch_creation_is_capped(self, api):
        with pytest.raises(ValueError, match="Maximum 100"):
            api.create_pull_requests_batch(3, [{}] * 101)

    def test_patch_pull_request(self, api, session):
        session.patch.return_value = make_response(SAMPLE_PR)

        api.patch_pull_request(4, 1, 5, {"state": "REJECTED", "state_cause": "no spec"})

        assert session.patch.call_args.args[0] == "/projects/4/repositories/triggers/1/pull_requests/5"
        assert session.patch.call_args.kwargs["json"] == {"state": "REJECTED", "state_cause": "no spec"}

    @pytest.mark.parametrize("status_code,created", [(201, True), (200, False)])
    def test_create_task_for_pull_request(self, api, session, status_code, created):
        session.post.return_value = make_response(SAMPLE_TASK, status_code)

        task, was_created = api.create_task_for_pull_request(4, 1, 5, '{"spec": {"image": "a/b:1"}}')

        assert task.id == 9 and was_created is created
        assert session.post.call_args.args == ("/projects/4/repositories/triggers/1/pull_requests/5/task",)
        assert session.post.call_args.kwargs["json"] == {"spec_raw": '{"spec": {"image": "a/b:1"}}'}


class TestDatasets:
    def test_get_datasets_unwraps_pagination(self, api, session):
        session.get.return_value = make_response({"items": [SAMPLE_DATASET]})

        datasets = api.get_datasets()

        assert [type(d) for d in datasets] == [Dataset]

    def test_get_datasets_accepts_a_bare_list(self, api, session):
        session.get.return_value = make_response([SAMPLE_DATASET])

        assert len(api.get_datasets()) == 1

    def test_get_dataset(self, api, session):
        session.get.return_value = make_response(SAMPLE_DATASET)

        assert api.get_dataset(1).name == "cdm"
        session.get.assert_called_once_with("/global/datasets/1")

    def test_get_project_dataset_finds_the_assignment_by_dataset_id(self, api, session):
        assignment = {"project_id": 1, "dataset": SAMPLE_DATASET, "enabled": True, "revoked": False, "active": True}
        session.get.return_value = make_response(assignment)

        found = api.get_project_dataset(1, 1)

        assert isinstance(found, ProjectDataset) and found.dataset.id == 1
        session.get.assert_called_once_with("/projects/1/datasets/1")

    def test_create_dataset(self, api, session):
        session.post.return_value = make_response(SAMPLE_DATASET)

        api.create_dataset(
            name="cdm", host="db.host", port=5432, db_type="postgres",
            secret_label="cdm-creds", read_schema="cdm",
        )

        assert session.post.call_args.args == ("/global/datasets",)
        assert session.post.call_args.kwargs["json"] == {
            "name": "cdm", "host": "db.host", "port": 5432, "type": "postgres",
            "secret_label": "cdm-creds", "read_schema": "cdm", "write_schema": None,
        }


SAMPLE_PROJECT = {"id": 1, "name": "proj", "enabled": True, "default_dataset_id": 1}
SAMPLE_TASK = {
    "id": 9, "name": "t", "spec": {"image": "a/b:1", "dataset_id": 1, "env": {}}, "attempt": 1, "trigger_id": 4, "status": "PENDING", "requested_by": "u",
    "project_id": 1, "dagster_run_id": None, "exit_code": None,
    "started_at": None, "completed_at": None,
}


def page(items, pages, key="items"):
    return make_response({key: items, "page": 1, "per_page": 100, "total": len(items), "pages": pages})


class TestProjects:
    def test_get_projects_follows_the_pages(self, api, session):
        second = {**SAMPLE_PROJECT, "id": 2, "enabled": False}
        session.get.side_effect = [page([SAMPLE_PROJECT], 2), page([second], 2)]

        projects = api.get_projects()

        assert [(p.id, p.enabled) for p in projects] == [(1, True), (2, False)]
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_filters_are_sent_as_query_options(self, api, session):
        session.get.return_value = page([], 0)

        api.get_projects(enabled=True, locked=False)

        assert session.get.call_args.kwargs["params"] == {"enabled": "true", "locked": "false", "page": 1, "per_page": 100}

    def test_no_projects(self, api, session):
        session.get.return_value = page([], 0)

        assert api.get_projects() == []


class TestTasks:
    def test_get_tasks_filters_by_status_and_project(self, api, session):
        session.get.return_value = page([SAMPLE_TASK], 1, key="tasks")

        tasks = api.get_tasks(status="PENDING", project_id=1)

        assert [t.id for t in tasks] == [9]
        assert session.get.call_args.args == ("/tasks",)
        params = session.get.call_args.kwargs["params"]
        assert (params["status"], params["project_id"]) == ("PENDING", 1)

    def test_get_tasks_follows_the_pages(self, api, session):
        second = {**SAMPLE_TASK, "id": 10}
        session.get.side_effect = [page([SAMPLE_TASK], 2, key="tasks"), page([second], 2, key="tasks")]

        tasks = api.get_tasks(status="PENDING", project_id=1)

        assert [t.id for t in tasks] == [9, 10]
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_patch_task_reads_the_run_fields(self, api, session):
        session.patch.return_value = make_response({**SAMPLE_TASK, "dagster_run_id": "r1", "exit_code": 0})

        task = api.patch_task(9, {"status": "QUEUED"})

        assert (task.dagster_run_id, task.exit_code) == ("r1", 0)
        assert session.patch.call_args.args == ("/tasks/9",)
        assert session.patch.call_args.kwargs["json"] == {"status": "QUEUED"}


class TestResults:
    RESULT = {"id": 9, "type": "PR", "task_id": 7, "project_id": 1, "results_repository_id": 5, "step": "UNKNOWN", "state": "IN_PROGRESS",
              "attempts": 0}

    ASSIGNMENT = {
        "project_id": 1,
        "results_repository": {
            "id": 2, "uri": "h/o/r", "provider": "gitea", "api_uri": "http://h/api/v1", "secret": SAMPLE_SECRET, "enabled": True,
        },
        "target_dir": "results", "owned_by_federated_node": True, "enabled": True, "revoked": False, "active": True,
    }

    def test_the_results_repository_is_the_assignment_of_the_project(self, api, session):
        session.get.return_value = make_response([self.ASSIGNMENT])

        result = api.get_results_repository(1)

        session.get.assert_called_once_with("/projects/1/repositories/results")
        assert (result.results_repository.id, result.target_dir) == (2, "results")

    def test_an_inactive_assignment_is_still_returned(self, api, session):
        session.get.return_value = make_response([{**self.ASSIGNMENT, "revoked": True, "active": False}])

        assert api.get_results_repository(1).active is False

    def test_the_results_repository_is_fetched_by_project_and_assignment_id(self, api, session):
        session.get.return_value = make_response(self.ASSIGNMENT)

        result = api.get_results_repository_by_id(1, 2)

        session.get.assert_called_once_with("/projects/1/repositories/results/2")
        assert result.results_repository.id == 2

    def test_create_posts_the_task_and_repository(self, api, session):
        session.post.return_value = make_response(self.RESULT)

        api.create_result(1, 7, 5)

        session.post.assert_called_once_with("/projects/1/results", json={"task_id": 7, "results_repository_id": 5})

    def test_patch_and_list(self, api, session):
        session.patch.return_value = make_response({**self.RESULT, "step": "PUSHED"})
        session.get.return_value = make_response([self.RESULT])

        assert api.patch_result(1, 9, {"step": "PUSHED"}).step == PullRequestResultStep.PUSHED
        assert api.get_task_results(7)[0].id == 9
        session.patch.assert_called_once_with("/projects/1/results/9", json={"step": "PUSHED"})
        session.get.assert_called_once_with("/tasks/7/results")

    def test_list_by_step(self, api, session):
        session.get.return_value = make_response([{**self.RESULT, "step": "OPENED"}])

        (result,) = api.get_results_by_step(1, ["PUSHED", "OPENED"])

        assert result.step == PullRequestResultStep.OPENED
        session.get.assert_called_once_with("/projects/1/results", params={"step": ["PUSHED", "OPENED"]})
