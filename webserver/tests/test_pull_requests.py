"""Pull requests stored once per global trigger repository: the ingest, the cursors, the delete guard."""
from datetime import datetime
from http import HTTPStatus

import pytest
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.helpers.pull_request_fanout import store_pull_request
from app.models.pull_request import PullRequest, PullRequestFile
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.trigger import Trigger
from tests.helpers.pull_requests import pr_body


def batch_url(repo_id):
    return f"/trigger_repositories/{repo_id}/pull_requests/batch"


def counts():
    return PullRequest.query.count(), PullRequestFile.query.count(), PullRequestTrigger.query.count(), Trigger.query.count()


@pytest.fixture
def batch():
    return [pr_body(1, "2026-01-01T10:00:00Z"), pr_body(2, "2026-03-05T11:30:00Z")]


class TestGlobalBatch:
    def test_stores_the_facts_once_and_fans_out(self, client, post_json_admin_header, default_repo, batch):
        response = client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": batch}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.CREATED
        assert response.json == {"created": [1, 2], "existing": []}
        # Two pull requests, a file each, and the one assignment's trigger for each
        assert counts() == (2, 2, 2, 2)

    def test_reposting_the_same_batch_is_a_no_op(self, client, post_json_admin_header, default_repo, batch):
        url = batch_url(default_repo.trigger_repository_id)
        client.post(url, json={"pull_requests": batch}, headers=post_json_admin_header)
        before = counts()
        again = client.post(url, json={"pull_requests": batch}, headers=post_json_admin_header)
        assert again.status_code == HTTPStatus.CREATED
        assert again.json == {"created": [], "existing": [1, 2]}
        assert counts() == before

    def test_a_known_number_keeps_its_facts_and_a_new_one_is_added(self, client, post_json_admin_header, default_repo, batch):
        url = batch_url(default_repo.trigger_repository_id)
        client.post(url, json={"pull_requests": batch}, headers=post_json_admin_header)
        response = client.post(
            url, json={"pull_requests": [pr_body(1, "2026-01-01T10:00:00Z", title="changed"), pr_body(3, "2026-04-01T10:00:00Z")]},
            headers=post_json_admin_header,
        )
        assert response.json == {"created": [3], "existing": [1]}
        assert PullRequest.query.filter_by(number=1).one().title == "PR 1"

    def test_a_number_twice_in_one_batch_is_stored_once(self, client, post_json_admin_header, default_repo):
        response = client.post(
            batch_url(default_repo.trigger_repository_id), json={"pull_requests": [pr_body(1), pr_body(1)]},
            headers=post_json_admin_header,
        )
        assert response.json == {"created": [1], "existing": [1]}
        assert counts()[0] == 1

    def test_the_same_number_in_two_repositories_is_two_pull_requests(
        self, client, post_json_admin_header, default_repo, assign_trigger
    ):
        other = assign_trigger("github.com/org/other")
        for repo in (default_repo, other):
            client.post(batch_url(repo.trigger_repository_id), json={"pull_requests": [pr_body(1)]}, headers=post_json_admin_header)
        assert PullRequest.query.count() == 2

    def test_a_bad_pull_request_keeps_nothing_of_the_batch(self, client, post_json_admin_header, default_repo):
        bad = pr_body(2)
        del bad["base_branch"]
        response = client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": [pr_body(1), bad]}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert counts() == (0, 0, 0, 0)

    @pytest.mark.parametrize("field,value", [
        ("number", "1"), ("merged_at", "yesterday"), ("files_truncated", "no"), ("changed_files", [{"path": "a.json"}]),
        ("changed_files", ["a.json"]), ("merge_commit_sha", "a" * 41), ("unknown", 1),
    ])
    def test_invalid_fields(self, client, post_json_admin_header, default_repo, field, value):
        response = client.post(
            batch_url(default_repo.trigger_repository_id), json={"pull_requests": [{**pr_body(1), field: value}]},
            headers=post_json_admin_header,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_at_most_100(self, client, post_json_admin_header, default_repo):
        response = client.post(
            batch_url(default_repo.trigger_repository_id), json={"pull_requests": [pr_body(n) for n in range(101)]},
            headers=post_json_admin_header,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_not_a_list(self, client, post_json_admin_header, default_repo):
        response = client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": {}}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_repository(self, client, post_json_admin_header):
        assert client.post(batch_url(9999), json={"pull_requests": []}, headers=post_json_admin_header).status_code == HTTPStatus.NOT_FOUND

    def test_needs_auth(self, client, default_repo):
        assert client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": []}).status_code == HTTPStatus.UNAUTHORIZED


class TestStorePullRequest:
    def facts(self, repo_id, number=1):
        body = pr_body(number, merged_at=datetime(2026, 1, 1, 10))
        return {"trigger_repository_id": repo_id, **body}

    def test_the_second_store_of_a_number_returns_the_stored_one(self, client, trigger_repo):
        first, created = store_pull_request(**self.facts(trigger_repo.id))
        second, created_again = store_pull_request(**self.facts(trigger_repo.id))
        assert (created, created_again, second.id) == (True, False, first.id)
        assert PullRequest.query.count() == 1


class TestListPullRequests:
    def test_the_facts_most_recent_first(self, client, post_json_admin_header, simple_admin_header, default_repo, batch):
        client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": batch}, headers=post_json_admin_header)
        response = client.get(f"/trigger_repositories/{default_repo.trigger_repository_id}/pull_requests", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert [pr["number"] for pr in response.json["items"]] == [2, 1]
        assert (response.json["page"], response.json["per_page"], response.json["total"]) == (1, 20, 2)
        assert response.json["items"][0]["base_branch"] == "main"
        second = client.get(f"/trigger_repositories/{default_repo.trigger_repository_id}/pull_requests?per_page=1&page=2", headers=simple_admin_header)
        assert [pr["number"] for pr in second.json["items"]] == [1]

    def test_unknown_repository(self, client, simple_admin_header):
        assert client.get("/trigger_repositories/9999/pull_requests", headers=simple_admin_header).status_code == HTTPStatus.NOT_FOUND


class TestCursors:
    def test_the_global_cursor_is_the_latest_merge_and_the_assignment_cursor_is_its_own(
        self, client, post_json_admin_header, simple_admin_header, default_repo, batch
    ):
        repo_id = default_repo.trigger_repository_id
        assert client.get(f"/trigger_repositories/{repo_id}", headers=simple_admin_header).json["pr_cursor"] is None

        client.post(batch_url(repo_id), json={"pull_requests": batch}, headers=post_json_admin_header)
        assert client.get(f"/trigger_repositories/{repo_id}", headers=simple_admin_header).json["pr_cursor"] == "2026-03-05T11:30:00Z"

        # A pull request the assignment has no trigger for, as one before its cursor has none
        later = pr_body(9, "2026-06-01T00:00:00Z")
        default_repo.enabled = False
        db.session.commit()
        client.post(batch_url(repo_id), json={"pull_requests": [later]}, headers=post_json_admin_header)
        assert client.get(f"/trigger_repositories/{repo_id}", headers=simple_admin_header).json["pr_cursor"] == "2026-06-01T00:00:00Z"
        assignment = client.get(f"/projects/{default_repo.project_id}/trigger_repositories/{default_repo.id}", headers=simple_admin_header).json
        assert assignment["pr_cursor"] == "2026-03-05T11:30:00Z"

    def test_the_global_cursor_is_the_maximum_whatever_the_order_of_arrival(self, client, post_json_admin_header, simple_admin_header, trigger_repo):
        client.post(batch_url(trigger_repo.id), json={"pull_requests": [pr_body(2, "2026-03-05T11:30:00Z")]}, headers=post_json_admin_header)
        client.post(batch_url(trigger_repo.id), json={"pull_requests": [pr_body(1, "2026-01-01T10:00:00Z")]}, headers=post_json_admin_header)
        assert client.get(f"/trigger_repositories/{trigger_repo.id}", headers=simple_admin_header).json["pr_cursor"] == "2026-03-05T11:30:00Z"

    def test_a_new_assignment_starts_after_the_latest_stored_pull_request(
        self, client, post_json_admin_header, simple_admin_header, project, trigger_repo, batch
    ):
        client.post(batch_url(trigger_repo.id), json={"pull_requests": batch}, headers=post_json_admin_header)
        created = client.post(
            f"/projects/{project.id}/trigger_repositories", json={"trigger_repository_id": trigger_repo.id, "watch_dir": ""},
            headers=post_json_admin_header,
        )
        assert created.status_code == HTTPStatus.CREATED
        assert created.json["initial_cursor"] == "2026-03-05T11:30:00"
        assert (created.json["pr_cursor"], created.json["pr_count"]) == ("2026-03-05T11:30:00Z", 0)


class TestDeleteAssignmentWithTriggers:
    def test_refused_while_triggers_exist(
        self, client, post_json_admin_header, simple_admin_header, lock_project, default_repo, batch
    ):
        client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": batch}, headers=post_json_admin_header)
        response = client.delete(f"/projects/{lock_project.id}/trigger_repositories/{default_repo.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert counts() == (2, 2, 2, 2)

    def test_the_database_refuses_it_too(self, client, post_json_admin_header, default_repo, batch):
        client.post(batch_url(default_repo.trigger_repository_id), json={"pull_requests": batch}, headers=post_json_admin_header)
        with pytest.raises(IntegrityError):
            db.session.delete(default_repo)
            db.session.commit()
        db.session.rollback()

    def test_allowed_once_there_are_none(self, client, simple_admin_header, lock_project, default_repo):
        response = client.delete(f"/projects/{lock_project.id}/trigger_repositories/{default_repo.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.NO_CONTENT
