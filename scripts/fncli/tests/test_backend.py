from unittest.mock import MagicMock

import pytest

from fncli.dagster.backend import BackendAPI
from fncli.dagster.models import Dataset

SECRET = {"id": 3, "project_id": 1, "label": "l", "provider": "K8S", "key": "k", "namespace": "fn"}
REPO = {
    "id": 1, "uri": "gitea.fn.svc/gitea_admin/trigger", "provider": "gitea", "api_uri": "http://x/api/v1",
    "secret": SECRET, "watch_dir": "specs/", "base_branch": "main", "project_id": 1,
    "pr_cursor": "2026-01-01T00:00:00Z",
}
DATASET = {
    "id": 1, "secret": SECRET, "name": "cdm", "host": "db", "port": 5432,
    "type": "postgres", "slug": "cdm", "url": "https://db/cdm",
}


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def api(session):
    return BackendAPI(session=session, logger=MagicMock())


def test_create_dataset_body(api, session):
    session.post.return_value = response(DATASET)

    api.create_dataset(
        name="cdm", host="db", port=5432, db_type="postgres",
        secret_label="creds", read_schema="cdm",
    )

    assert session.post.call_args.args == ("/datasets",)
    assert session.post.call_args.kwargs["json"] == {
        "name": "cdm", "host": "db", "port": 5432, "type": "postgres",
        "secret_label": "creds", "read_schema": "cdm", "write_schema": None,
    }


ASSIGNMENT = {"id": 5, "project_id": 7, "dataset": DATASET, "enabled": True, "revoked": False, "active": True}


class TestProjectDatasets:
    def test_find_project_dataset_by_name_is_case_insensitive(self, api, session):
        session.get.return_value = response([ASSIGNMENT])

        assert api.find_project_dataset("CDM", 7).id == 5
        assert api.find_project_dataset("other", 7) is None
        assert session.get.call_args.args == ("/projects/7/datasets",)

    def test_get_or_assign_reuses_an_existing_assignment(self, api, session):
        session.get.return_value = response([ASSIGNMENT])
        dataset = api.find_project_dataset("cdm", 7).dataset

        assert api.get_or_assign_dataset(7, dataset).id == 5
        session.post.assert_not_called()

    def test_get_or_assign_assigns_when_missing(self, api, session):
        session.get.return_value = response([])
        session.post.return_value = response(ASSIGNMENT)
        dataset = Dataset(**DATASET)

        assert api.get_or_assign_dataset(7, dataset).project_id == 7
        assert session.post.call_args.args == ("/projects/7/datasets",)
        assert session.post.call_args.kwargs["json"] == {"dataset_id": 1}


class TestGetOrCreateRepository:
    def create(self, api, uri):
        return api.get_or_create_repository(
            uri=uri, project_id=1, provider="gitea", api_uri="http://x/api/v1", secret_label="l",
            watch_dir="specs/", base_branch="main",
        )

    @pytest.mark.parametrize("uri", [
        "http://gitea.fn.svc/gitea_admin/trigger",
        "https://gitea.fn.svc/gitea_admin/trigger/",
        "https://Gitea.FN.svc/gitea_admin/Trigger",
        "gitea.fn.svc/gitea_admin/trigger",
    ])
    def test_an_existing_repository_is_matched_with_the_scheme_stripped_and_lowercased(
        self, api, session, uri
    ):
        session.get.return_value = response([REPO])

        repo = self.create(api, uri)

        assert repo.id == 1
        session.post.assert_not_called()

    def test_a_scheme_less_uri_with_a_port_is_matched(self, api, session):
        session.get.return_value = response([{**REPO, "uri": "gitea.fn.svc:3000/gitea_admin/trigger"}])

        self.create(api, "gitea.fn.svc:3000/gitea_admin/trigger")

        session.post.assert_not_called()

    def test_a_repository_of_another_project_is_not_reused(self, api, session):
        session.get.return_value = response([{**REPO, "project_id": 2}])
        session.post.return_value = response(REPO)

        self.create(api, "http://gitea.fn.svc/gitea_admin/trigger")

        session.post.assert_called_once()
        body = session.post.call_args.kwargs["json"]
        assert body["uri"] == "http://gitea.fn.svc/gitea_admin/trigger"
        assert body["secret_label"] == "l" and body["project_id"] == 1

    def test_a_different_uri_creates(self, api, session):
        session.get.return_value = response([REPO])
        session.post.return_value = response(REPO)

        self.create(api, "http://gitea.fn.svc/gitea_admin/other")

        session.post.assert_called_once()


def test_get_task_results_lists_the_tasks_deliveries(api, session):
    body = [{
        "id": 4, "type": "PR", "task_id": 9, "results_repository_id": 2, "step": "OPENED", "state": "DELIVERED",
        "attempts": 1,
        "branch": None, "commit_sha": "abc", "number": None, "url": None,
        "error": None, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }]
    session.get.return_value = response(body)

    results = api.get_task_results(9)

    session.get.assert_called_once_with("/tasks/9/results")
    assert [(r.id, r.step, r.state, r.commit_sha) for r in results] == [(4, "OPENED", "DELIVERED", "abc")]
