from unittest.mock import MagicMock

import pytest

from app.backend import BackendAPI
from app.models import Dataset, PullRequest, TriggerRepository
from app.tests.conftest import SAMPLE_PR, SAMPLE_REPOSITORY_OBJ, make_response


SAMPLE_DATASET = {
    "id": 1,
    "project_id": 1,
    "name": "cdm",
    "host": "db.host",
    "port": 5432,
    "k8s_secret_name": "cdm-creds",
    "read_schema": "cdm",
    "write_schema": "results",
    "type": "postgres",
    "slug": "cdm",
    "url": "https://db.host/cdm",
}



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

        repos = api.get_repositories()

        assert [type(r) for r in repos] == [TriggerRepository]
        assert repos[0].path == "org/repo"

    def test_get_repository(self, api, session):
        session.get.return_value = make_response(SAMPLE_REPOSITORY_OBJ)

        assert api.get_repository(1).id == 1
        session.get.assert_called_once_with("/trigger_repositories/1")

    def test_patch_repository(self, api, session):
        session.patch.return_value = make_response(SAMPLE_REPOSITORY_OBJ)

        api.patch_repository(1, {"pr_cursor": "2026-07-01T00:00:00Z"})

        assert session.patch.call_args.args[0] == "/trigger_repositories/1"
        assert session.patch.call_args.kwargs["json"] == {
            "pr_cursor": "2026-07-01T00:00:00Z"
        }

    def test_delete_repository(self, api, session):
        api.delete_repository(3)

        session.delete.assert_called_once_with("/trigger_repositories/3")


class TestPullRequests:
    def _page(self, prs, total):
        return make_response({"items": prs, "total": total})

    def test_single_page(self, api, session):
        session.get.return_value = self._page([SAMPLE_PR], 1)

        prs = api.get_pull_requests(repo_id=1, state="UNKNOWN")

        assert [type(p) for p in prs] == [PullRequest]
        assert session.get.call_count == 1

    def test_pagination_follows_the_total(self, api, session):
        second = {**SAMPLE_PR, "number": 6}
        session.get.side_effect = [self._page([SAMPLE_PR], 2), self._page([second], 2)]

        prs = api.get_pull_requests(repo_id=1, state="UNKNOWN")

        assert [p.number for p in prs] == [5, 6]
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_pagination_stops_on_an_empty_page(self, api, session):
        session.get.side_effect = [self._page([SAMPLE_PR], 99), self._page([], 99)]

        assert len(api.get_pull_requests(repo_id=1, state="UNKNOWN")) == 1

    def test_the_state_is_sent_as_a_query_param(self, api, session):
        session.get.return_value = self._page([], 0)

        api.get_pull_requests(repo_id=1, state="UNKNOWN")

        assert session.get.call_args.kwargs["params"]["state"] == "UNKNOWN"

    def test_create_pull_request(self, api, session):
        session.post.return_value = make_response(SAMPLE_PR)

        api.create_pull_request(
            trigger_repository_id=1,
            number=5,
            title="t",
            raised_by="dev",
            merged_at="2026-06-26T10:00:00Z",
            merge_commit_sha="abc",
            payload={},
        )

        body = session.post.call_args.kwargs["json"]
        assert "status" not in body and "state" not in body
        assert body["number"] == 5

    def test_batch_creation_is_capped(self, api):
        with pytest.raises(ValueError, match="Maximum 100"):
            api.create_pull_requests_batch(1, [SAMPLE_PR] * 101)

    def test_batch_creation(self, api, session):
        session.post.return_value = make_response([SAMPLE_PR])

        prs = api.create_pull_requests_batch(1, [SAMPLE_PR])

        assert session.post.call_args.args[0] == "/trigger_repositories/1/pull_requests/batch"
        assert len(prs) == 1

    def test_patch_pull_request(self, api, session):
        session.patch.return_value = make_response(SAMPLE_PR)

        api.patch_pull_request(1, 5, {"state": "IGNORED", "state_cause": "no spec"})

        assert session.patch.call_args.args[0] == "/trigger_repositories/1/pull_requests/5"
        assert session.patch.call_args.kwargs["json"] == {"state": "IGNORED", "state_cause": "no spec"}

    @pytest.mark.parametrize("status_code,created", [(201, True), (200, False)])
    def test_create_task_for_pull_request(self, api, session, status_code, created):
        session.post.return_value = make_response(SAMPLE_TASK, status_code)

        task, was_created = api.create_task_for_pull_request(1, 5, {"image": "a/b:1"})

        assert task.id == 9 and was_created is created
        assert session.post.call_args.args == ("/trigger_repositories/1/pull_requests/5/task",)
        assert session.post.call_args.kwargs["json"] == {"payload": {"image": "a/b:1"}}


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
        session.get.assert_called_once_with("/datasets/1")

    def test_get_dataset_by_name_swallows_failures(self, api, session):
        session.get.side_effect = RuntimeError("404")

        assert api.get_dataset_by_name("nope") is None

    def test_create_dataset(self, api, session):
        session.post.return_value = make_response(SAMPLE_DATASET)

        api.create_dataset(
            name="cdm", host="db.host", port=5432, k8s_secret_name="cdm-creds",
            read_schema="cdm", db_type="postgres",
        )

        assert session.post.call_args.kwargs["json"]["type"] == "postgres"


class TestRequests:
    def test_create_request_returns_the_raw_response(self, api, session):
        response = make_response({"id": 1})
        session.post.return_value = response

        assert api.create_request(
            title="t", description="d", project_name="p", requested_by="dev",
            proj_start="2026-01-01", proj_end="2026-02-01", dataset_id=1,
        ) is response
        assert session.post.call_args.kwargs["raise_for_status"] is False

    def test_approve_request(self, api, session):
        assert api.approve_request(7) is True
        assert session.patch.call_args.args[0] == "/requests/7"
        assert session.patch.call_args.kwargs["json"] == {"status": "approved"}


SAMPLE_PROJECT = {"id": 1, "name": "proj", "enabled": True, "default_dataset_id": 1}
SAMPLE_TASK = {
    "id": 9, "name": "t", "docker_image": "a/b:1", "spec": {"image": "a/b:1"}, "attempt": 1, "trigger_id": 4, "status": "PENDING", "requested_by": "u",
    "dataset_id": 1, "project_id": 1, "dagster_run_id": None, "exit_code": None,
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
