from unittest.mock import MagicMock

import pytest

from app.backend import BackendAPI
from app.models import Dataset, PullRequest, Registry, TriggerRepository
from app.tests.conftest import SAMPLE_PR, SAMPLE_REPOSITORY_OBJ, make_response


SAMPLE_DATASET = {
    "id": 1,
    "name": "cdm",
    "host": "db.host",
    "port": 5432,
    "schema": "cdm",
    "schema_write": "results",
    "type": "postgres",
    "slug": "cdm",
    "url": "https://db.host/cdm",
}

SAMPLE_REGISTRY = {"id": 1, "url": "ghcr.io", "active": True, "needs_auth": True}


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

        prs = api.get_pull_requests(repo_id=1)

        assert [type(p) for p in prs] == [PullRequest]
        assert session.get.call_count == 1

    def test_pagination_follows_the_total(self, api, session):
        second = {**SAMPLE_PR, "number": 6}
        session.get.side_effect = [self._page([SAMPLE_PR], 2), self._page([second], 2)]

        prs = api.get_pull_requests(repo_id=1)

        assert [p.number for p in prs] == [5, 6]
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_pagination_stops_on_an_empty_page(self, api, session):
        session.get.side_effect = [self._page([SAMPLE_PR], 99), self._page([], 99)]

        assert len(api.get_pull_requests(repo_id=1)) == 1

    def test_query_params_are_forwarded(self, api, session):
        session.get.return_value = self._page([], 0)

        api.get_pull_requests(repo_id=1, status="UNKNOWN")

        assert session.get.call_args.kwargs["params"]["status"] == "UNKNOWN"

    def test_create_pull_request(self, api, session):
        session.post.return_value = make_response(SAMPLE_PR)

        api.create_pull_request(
            trigger_repository_id=1,
            number=5,
            title="t",
            raised_by="dev",
            merged_at="2026-06-26T10:00:00Z",
            merge_commit_sha="abc",
            spec={},
        )

        body = session.post.call_args.kwargs["json"]
        assert body["status"] == "UNKNOWN"
        assert body["number"] == 5

    def test_batch_creation_is_capped(self, api):
        with pytest.raises(ValueError, match="Maximum 100"):
            api.create_pull_requests_batch(1, [SAMPLE_PR] * 101)

    def test_batch_creation(self, api, session):
        session.post.return_value = make_response([SAMPLE_PR])

        prs = api.create_pull_requests_batch(1, [SAMPLE_PR])

        assert session.post.call_args.args[0] == "/trigger_repositories/1/pull_requests/batch"
        assert len(prs) == 1

    def test_update_status(self, api, session):
        session.patch.return_value = make_response(SAMPLE_PR)

        api.update_pull_request_status(1, 5, "SUCCESS")

        assert session.patch.call_args.args[0] == "/trigger_repositories/1/pull_requests/5"
        assert session.patch.call_args.kwargs["json"] == {"status": "SUCCESS"}


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
            name="cdm", host="db.host", port=5432, username="u",
            password="p", schema="cdm", db_type="postgres",
        )

        assert session.post.call_args.kwargs["json"]["type"] == "postgres"


class TestRegistries:
    def test_get_registries_unwraps_pagination(self, api, session):
        session.get.return_value = make_response({"items": [SAMPLE_REGISTRY]})

        registries = api.get_registries()

        assert [type(r) for r in registries] == [Registry]
        assert registries[0].secret_name == "ghcr-io"
        session.get.assert_called_once_with("/registries")

    def test_get_registries_accepts_a_bare_list(self, api, session):
        session.get.return_value = make_response([SAMPLE_REGISTRY])

        assert len(api.get_registries()) == 1

    def test_no_registries_configured(self, api, session):
        session.get.return_value = make_response({"items": []})

        assert api.get_registries() == []


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
