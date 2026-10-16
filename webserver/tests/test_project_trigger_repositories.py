"""A project's trigger repositories: the assignments, /projects/<id>/trigger_repositories, and their pull requests."""
import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.dtos.trigger_repository import ProjectTriggerRepositoryDTO
from app.helpers.base_model import db
from app.helpers.const import SPEC_RAW_MAX_BYTES, TASK_ENV_MAX_BYTES
from app.models.dataset import Dataset
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request import PullRequest
from app.models.pull_request_trigger import PullRequestTrigger
from tests.helpers.pull_requests import add_pull_request_trigger, pr_body
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.task import Task
from app.models.task_spec import TaskSpec
from app.models.trigger import Trigger
from app.models.trigger_repository import TriggerRepository


@pytest.fixture
def repository(default_repo):
    """The project's assignment, which the pull requests below belong to."""
    return default_repo


@pytest.fixture
def default_dataset(project, repository):
    """The project's default dataset, which default_repo made."""
    return ProjectDataset.query.filter_by(project_id=project.id).one().dataset


def url(project, *rest):
    return "/".join([f"/projects/{project.id}/trigger_repositories", *map(str, rest)])


class TestListAssignments:
    def test_list_empty(self, client, simple_admin_header, project):
        assert client.get(url(project), headers=simple_admin_header).json == []

    def test_list_returns_the_assignment_with_the_repository_nested(
        self, client, simple_admin_header, project, trigger_repo, repository, default_dataset
    ):
        response = client.get(url(project), headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == [ProjectTriggerRepositoryDTO.from_model(repository).dump()]
        [item] = response.json
        assert set(item) == {
            "id", "project_id", "trigger_repository", "watch_dir", "base_branch", "dataset_id", "initial_cursor",
            "pr_cursor", "pr_count", "enabled", "revoked", "active",
        }
        assert (item["watch_dir"], item["base_branch"], item["active"]) == ("", "main", True)
        assert item["trigger_repository"]["id"] == trigger_repo.id
        assert item["dataset_id"] == default_dataset.id

    def test_list_returns_an_inactive_assignment_with_flags(self, client, simple_admin_header, project, repository):
        repository.revoked = True
        db.session.commit()
        [item] = client.get(url(project), headers=simple_admin_header).json
        assert (item["enabled"], item["revoked"], item["active"]) == (True, True, False)

    def test_list_is_the_projects_own(self, client, simple_admin_header, other_project, repository):
        assert client.get(url(other_project), headers=simple_admin_header).json == []

    def test_project_not_found(self, client, simple_admin_header):
        assert client.get("/projects/9999/trigger_repositories", headers=simple_admin_header).status_code == 404

    def test_get_by_assignment_id(self, client, simple_admin_header, project, repository, other_project):
        assert client.get(url(project, repository.id), headers=simple_admin_header).status_code == 200
        assert client.get(url(other_project, repository.id), headers=simple_admin_header).status_code == 404

    def test_requires_auth(self, client, project):
        assert client.get(url(project)).status_code == 401


class TestListAllActiveAssignments:
    URL = "/project_trigger_repositories"

    def test_lists_every_projects_assignments(self, client, simple_admin_header, repository, other_project, assign_trigger):
        other = assign_trigger("github.com/org/other", project=other_project)
        response = client.get(self.URL, headers=simple_admin_header)
        assert response.status_code == 200
        assert [(a["id"], a["project_id"]) for a in response.json] == [
            (repository.id, repository.project_id), (other.id, other_project.id)
        ]

    def test_filtered_by_active(self, client, simple_admin_header, repository, other_project, assign_trigger):
        revoked = assign_trigger("github.com/org/revoked", project=other_project)
        disabled = assign_trigger("github.com/org/disabled", project=other_project)
        revoked.revoked = True
        disabled.enabled = False
        db.session.commit()
        response = client.get(f"{self.URL}?active=true", headers=simple_admin_header)
        assert [a["id"] for a in response.json] == [repository.id]

    def test_filtered_by_enabled_project(self, client, simple_admin_header, repository):
        url_ = f"{self.URL}?project_enabled=true"
        assert client.get(url_, headers=simple_admin_header).json == []
        repository.project.enabled = True
        db.session.commit()
        assert [a["id"] for a in client.get(url_, headers=simple_admin_header).json] == [repository.id]

    def test_requires_auth(self, client):
        assert client.get(self.URL).status_code == 401


class TestAssign:
    def body(self, trigger_repo, **changes):
        return {"trigger_repository_id": trigger_repo.id, "watch_dir": "triggers", **changes}

    def test_assign(self, client, post_json_admin_header, project, trigger_repo):
        response = client.post(url(project), json=self.body(trigger_repo, watch_dir="./a//b/"), headers=post_json_admin_header)
        assert response.status_code == 201
        assert (response.json["watch_dir"], response.json["base_branch"]) == ("a/b", "main")
        assert (response.json["enabled"], response.json["revoked"], response.json["active"]) == (True, False, True)
        assert response.json["trigger_repository"]["uri"] == trigger_repo.uri
        assert response.json["project_id"] == project.id
        assert ProjectTriggerRepository.query.count() == 1

    def test_assign_needs_no_lock_and_no_drain(self, client, post_json_admin_header, project, trigger_repo, make_task):
        project.locked = False
        make_task(status="RUNNING")
        response = client.post(url(project), json=self.body(trigger_repo), headers=post_json_admin_header)
        assert response.status_code == 201

    def test_assign_with_a_branch_and_cursor(self, client, post_json_admin_header, project, trigger_repo, default_dataset):
        body = self.body(trigger_repo, base_branch="develop", initial_cursor="2026-01-01T00:00:00", enabled=False)
        response = client.post(url(project), json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["base_branch"] == "develop"
        assert response.json["initial_cursor"] == "2026-01-01T00:00:00"
        assert response.json["pr_cursor"] == "2026-01-01T00:00:00Z"
        assert (response.json["enabled"], response.json["active"]) == (False, False)

    def test_assign_reports_the_projects_default_dataset(self, client, post_json_admin_header, project, trigger_repo, dataset):
        response = client.post(url(project), json=self.body(trigger_repo), headers=post_json_admin_header)
        assert response.json["dataset_id"] == dataset.id

    @pytest.mark.parametrize("missing", ["trigger_repository_id", "watch_dir"])
    def test_assign_requires_field(self, client, post_json_admin_header, project, trigger_repo, missing):
        body = self.body(trigger_repo)
        del body[missing]
        assert client.post(url(project), json=body, headers=post_json_admin_header).status_code == 400

    @pytest.mark.parametrize("extra", [{"project_id": 2}, {"uri": "github.com/a/b"}, {"revoked": True}])
    def test_assign_rejects_other_fields(self, client, post_json_admin_header, project, trigger_repo, extra):
        response = client.post(url(project), json=self.body(trigger_repo, **extra), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_assign_rejects_an_empty_base_branch(self, client, post_json_admin_header, project, trigger_repo):
        response = client.post(url(project), json=self.body(trigger_repo, base_branch=""), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_assign_rejects_a_bad_cursor(self, client, post_json_admin_header, project, trigger_repo):
        response = client.post(url(project), json=self.body(trigger_repo, initial_cursor="soon"), headers=post_json_admin_header)
        assert response.status_code == 400
        assert ProjectTriggerRepository.query.count() == 0

    @pytest.mark.parametrize("watch_dir", ["tmp/../x", ".."])
    def test_assign_refuses_bad_directories(self, client, post_json_admin_header, project, trigger_repo, watch_dir):
        response = client.post(url(project), json=self.body(trigger_repo, watch_dir=watch_dir), headers=post_json_admin_header)
        assert response.status_code == 400

    def test_assign_unknown_repository(self, client, post_json_admin_header, project):
        response = client.post(url(project), json={"trigger_repository_id": 9999, "watch_dir": "x"}, headers=post_json_admin_header)
        assert response.status_code == 404

    def test_assign_unknown_project(self, client, post_json_admin_header, trigger_repo):
        response = client.post("/projects/9999/trigger_repositories", json=self.body(trigger_repo), headers=post_json_admin_header)
        assert response.status_code == 404

    def test_the_same_repository_and_directory_twice_is_a_conflict(self, client, post_json_admin_header, project, repository, trigger_repo):
        response = client.post(url(project), json=self.body(trigger_repo, watch_dir=""), headers=post_json_admin_header)
        assert response.status_code == 409
        assert ProjectTriggerRepository.query.count() == 1

    def test_the_same_repository_on_another_directory_is_fine(self, client, post_json_admin_header, project, repository, trigger_repo):
        response = client.post(url(project), json=self.body(trigger_repo), headers=post_json_admin_header)
        assert response.status_code == 201
        assert ProjectTriggerRepository.query.count() == 2

    def test_another_project_can_use_the_same_repository(self, client, post_json_admin_header, repository, other_project, trigger_repo):
        response = client.post(url(other_project), json=self.body(trigger_repo, watch_dir=""), headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["id"] != repository.id
        assert TriggerRepository.query.count() == 1

    def test_the_database_rejects_the_same_assignment_twice(self, repository):
        duplicate = ProjectTriggerRepository(repository.project_id, repository.trigger_repository_id, watch_dir="")
        with pytest.raises(IntegrityError):
            duplicate.add()
        db.session.rollback()

    def test_requires_auth(self, client, project, trigger_repo):
        assert client.post(url(project), json=self.body(trigger_repo)).status_code == 401


class TestPatchAssignment:
    def patch(self, client, headers, project, assignment, body):
        return client.patch(url(project, assignment.id), json=body, headers=headers)

    def test_update_base_branch_and_watch_dir(self, client, post_json_admin_header, project, repository, lock_project):
        response = self.patch(client, post_json_admin_header, project, repository, {"base_branch": "develop", "watch_dir": "/a/./b/"})
        assert response.status_code == 200
        assert (response.json["base_branch"], response.json["watch_dir"]) == ("develop", "a/b")

    @pytest.mark.parametrize("body", [{"base_branch": ""}, {"watch_dir": ""}, {"watch_dir": "a/../b"}])
    def test_empty_or_bad_values_fail(self, client, post_json_admin_header, project, repository, lock_project, body):
        assert self.patch(client, post_json_admin_header, project, repository, body).status_code == 400

    @pytest.mark.parametrize("body", [
        {}, {"project_id": 2}, {"trigger_repository_id": 2}, {"uri": "x"}, {"enabled": "yes"}, {"revoked": 1},
    ])
    def test_patch_rejects_other_fields(self, client, post_json_admin_header, project, repository, lock_project, body):
        assert self.patch(client, post_json_admin_header, project, repository, body).status_code == 400

    def test_a_change_needs_the_lock(self, client, post_json_admin_header, project, repository):
        response = self.patch(client, post_json_admin_header, project, repository, {"base_branch": "develop"})
        assert response.status_code == 409

    def test_a_change_needs_the_project_drained(self, client, post_json_admin_header, project, repository, lock_project, make_task):
        make_task(status="RUNNING")
        response = self.patch(client, post_json_admin_header, project, repository, {"enabled": False})
        assert response.status_code == 409

    def test_enabled_off_and_on(self, client, post_json_admin_header, project, repository, lock_project):
        response = self.patch(client, post_json_admin_header, project, repository, {"enabled": False})
        assert (response.json["enabled"], response.json["active"]) == (False, False)
        response = self.patch(client, post_json_admin_header, project, repository, {"enabled": True})
        assert response.json["active"] is True

    def test_revoke_is_immediate_and_leaves_enabled(self, client, post_json_admin_header, project, repository, make_task):
        make_task(project=project, status="RUNNING")
        response = self.patch(client, post_json_admin_header, project, repository, {"revoked": True})
        assert response.status_code == 200
        assert (response.json["enabled"], response.json["revoked"], response.json["active"]) == (True, True, False)
        response = self.patch(client, post_json_admin_header, project, repository, {"revoked": False})
        assert response.json["active"] is True

    def test_only_an_admin_revokes(self, client, post_json_user_header, project, repository):
        response = self.patch(client, post_json_user_header, project, repository, {"revoked": True})
        assert response.status_code == 403
        assert ProjectTriggerRepository.get_by_id(repository.id).revoked is False

    def test_not_found(self, client, post_json_admin_header, project):
        response = client.patch(url(project, 9999), json={"enabled": True}, headers=post_json_admin_header)
        assert response.status_code == 404

    def test_another_projects_assignment_is_not_found(self, client, post_json_admin_header, other_project, repository):
        response = client.patch(url(other_project, repository.id), json={"revoked": True}, headers=post_json_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client, project, repository):
        assert client.patch(url(project, repository.id), json={"revoked": True}).status_code == 401


class TestInitialCursor:
    def test_initial_cursor_set_on_creation(self, client, post_json_admin_header, project, trigger_repo):
        """initial_cursor is set to the current time when none is given"""
        response = client.post(
            url(project), json={"trigger_repository_id": trigger_repo.id, "watch_dir": "t"}, headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert isinstance(response.json["initial_cursor"], str)

    def test_initial_cursor_custom_value(self, client, post_json_admin_header, project, trigger_repo):
        custom_cursor = "2026-01-01T00:00:00"
        response = client.post(
            url(project), json={"trigger_repository_id": trigger_repo.id, "watch_dir": "t", "initial_cursor": custom_cursor},
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json["initial_cursor"] == custom_cursor

    def test_pr_cursor_equals_initial_cursor_with_no_pull_requests(self, client, simple_admin_header, project, repository):
        repository.initial_cursor = "2026-01-01T00:00:00"
        db.session.commit()
        item = client.get(url(project, repository.id), headers=simple_admin_header).json
        assert (item["pr_cursor"], item["pr_count"]) == ("2026-01-01T00:00:00Z", 0)
        assert item["initial_cursor"] == "2026-01-01T00:00:00"

    def test_pr_cursor_is_the_latest_merge_time(self, client, post_json_admin_header, simple_admin_header, project, repository):
        client.post(
            url(project, repository.id, "pull_requests", "batch"),
            json={"pull_requests": [pr_body(1, "2026-01-01T10:00:00Z"), pr_body(2, "2026-03-05T11:30:00Z")]},
            headers=post_json_admin_header
        )
        item = client.get(url(project, repository.id), headers=simple_admin_header).json
        assert (item["pr_cursor"], item["pr_count"]) == ("2026-03-05T11:30:00Z", 2)

    def test_pr_cursor_of_one_assignment_ignores_the_others(
        self, client, post_json_admin_header, simple_admin_header, project, repository, other_project, assign_trigger
    ):
        other = assign_trigger("github.com/org/other", project=other_project)
        client.post(
            url(other_project, other.id, "pull_requests", "batch"),
            json={"pull_requests": [pr_body(1, "2026-03-05T11:30:00Z")]}, headers=post_json_admin_header
        )
        item = client.get(url(project, repository.id), headers=simple_admin_header).json
        assert item["pr_count"] == 0
        assert item["pr_cursor"] == item["initial_cursor"][:19] + "Z"

    def test_pr_cursor_falls_back_to_initial_cursor(self, client, post_json_admin_header, simple_admin_header, project, repository, lock_project):
        client.patch(url(project, repository.id), json={"initial_cursor": "2026-02-02T02:02:02"}, headers=post_json_admin_header)
        item = client.get(url(project, repository.id), headers=simple_admin_header).json
        assert item["pr_cursor"] == "2026-02-02T02:02:02Z"

    def test_initial_cursor_can_only_move_earlier_once_pull_requests_exist(
        self, client, post_json_admin_header, project, repository, lock_project
    ):
        client.post(
            url(project, repository.id, "pull_requests", "batch"),
            json={"pull_requests": [pr_body()]}, headers=post_json_admin_header
        )
        later = client.patch(url(project, repository.id), json={"initial_cursor": "2026-02-02T02:02:02"}, headers=post_json_admin_header)
        assert later.status_code == 400
        earlier = client.patch(url(project, repository.id), json={"initial_cursor": "2025-12-01T00:00:00"}, headers=post_json_admin_header)
        assert earlier.status_code == 200


class TestDeleteAssignment:
    def test_unassign_keeps_the_repository(self, client, simple_admin_header, project, repository, lock_project):
        response = client.delete(url(project, repository.id), headers=simple_admin_header)
        assert response.status_code == 204
        assert ProjectTriggerRepository.query.count() == 0
        assert TriggerRepository.query.count() == 1

    def test_unassign_needs_the_lock(self, client, simple_admin_header, project, repository):
        assert client.delete(url(project, repository.id), headers=simple_admin_header).status_code == 409

    def test_restrict_blocks_the_delete_while_triggers_exist(
        self, client, post_json_admin_header, simple_admin_header, project, repository, lock_project
    ):
        client.post(
            url(project, repository.id, "pull_requests", "batch"),
            json={"pull_requests": [pr_body()]}, headers=post_json_admin_header
        )
        response = client.delete(url(project, repository.id), headers=simple_admin_header)
        assert response.status_code == 400
        assert ProjectTriggerRepository.query.count() == 1
        assert PullRequestTrigger.query.count() == 1
        assert Trigger.query.count() == 1

    def test_the_database_restricts_it_too(self, project, repository):
        add_pull_request_trigger(repository, 1, title="t", raised_by="u")
        with pytest.raises(IntegrityError):
            db.session.delete(repository)
            db.session.commit()
        db.session.rollback()

    def test_not_found(self, client, simple_admin_header, project, lock_project):
        assert client.delete(url(project, 9999), headers=simple_admin_header).status_code == 404


class TestLoopGuard:
    """A trigger assignment and a results assignment on the same repository must not overlap, across projects too."""

    def make_results(self, project, uri="github.com/org/test-repo", target_dir="results"):
        repo = ResultsRepository.query.filter_by(uri=uri).one_or_none()
        if repo is None:
            repo = ResultsRepository(uri=uri, provider="github", api_uri="https://api.github.com", secret_id=Secret.query.one().id)
            repo.add()
        return ProjectResultsRepository(project.id, repo.id, target_dir=target_dir).add()

    def assign(self, client, header, project, trigger_repo, **changes):
        body = {"trigger_repository_id": trigger_repo.id, "watch_dir": "triggers", **changes}
        return client.post(url(project), json=body, headers=header)

    @pytest.mark.parametrize("watch_dir,ok", [("triggers", True), ("results", False), ("results/in", False), ("res", True), ("", False)])
    def test_assigned_after_results(self, client, post_json_admin_header, project, trigger_repo, watch_dir, ok):
        self.make_results(project)
        response = self.assign(client, post_json_admin_header, project, trigger_repo, watch_dir=watch_dir)
        assert (response.status_code == 201) is ok
        assert ProjectTriggerRepository.query.count() == (1 if ok else 0)

    def test_a_results_assignment_in_another_project_is_refused_too(
        self, client, post_json_admin_header, project, other_project, trigger_repo
    ):
        self.make_results(other_project)
        response = self.assign(client, post_json_admin_header, project, trigger_repo, watch_dir="results")
        assert response.status_code == 400
        assert ProjectTriggerRepository.query.count() == 0

    def test_a_clear_directory_in_another_project_is_fine(self, client, post_json_admin_header, project, other_project, trigger_repo):
        self.make_results(other_project)
        assert self.assign(client, post_json_admin_header, project, trigger_repo, watch_dir="elsewhere").status_code == 201

    def test_different_remotes_are_fine(self, client, post_json_admin_header, project, trigger_repo):
        self.make_results(project, uri="github.com/org/elsewhere")
        assert self.assign(client, post_json_admin_header, project, trigger_repo, watch_dir="results").status_code == 201

    def test_patching_watch_dir_into_the_results_dir_is_refused(self, client, post_json_admin_header, project, repository, lock_project):
        self.make_results(project)
        repository.watch_dir = "triggers"
        db.session.commit()
        response = client.patch(url(project, repository.id), json={"watch_dir": "results/x"}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert ProjectTriggerRepository.get_by_id(repository.id).watch_dir == "triggers"

    def test_a_results_assignment_on_another_projects_trigger_is_refused(
        self, client, post_json_admin_header, project, other_project, results_repo, assign_trigger
    ):
        assign_trigger("github.com/org/results", watch_dir="results", project=other_project)
        project.locked = True
        db.session.commit()
        body = {"results_repository_id": results_repo.id, "target_dir": "results"}
        response = client.post(f"/projects/{project.id}/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert ProjectResultsRepository.query.count() == 0


class TestPostPullRequestsBatch:
    def test_batch_create_multiple_prs(self, client, post_json_admin_header, repository):
        """Test creating multiple PRs in a single batch request"""
        batch_data = [
            pr_body(1, "2026-01-01T10:00:00Z", title="First PR", raised_by="user1"),
            pr_body(2, "2026-01-02T10:00:00Z", title="Second PR", raised_by="user2"),
        ]
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": batch_data}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert len(response.json) == 2
        assert response.json[0]["number"] == 1
        assert response.json[1]["number"] == 2

    def test_batch_create_empty_list(self, client, post_json_admin_header, repository):
        """Test creating with empty list returns empty list"""
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": []}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json == []

    def test_batch_exceeds_max_count(self, client, post_json_admin_header, repository):
        """Test that batch creation fails if more than 100 PRs"""
        batch_data = [pr_body(i) for i in range(101)]
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": batch_data}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "Maximum 100" in response.json.get("error", "")

    def test_batch_missing_required_field(self, client, post_json_admin_header, repository):
        """Test that batch creation fails if a PR is missing required fields"""
        batch_data = [
            {
                "number": 1,
                "title": "PR without raised_by",
                # Missing 'raised_by', 'merged_at', 'merge_commit_sha'
            }
        ]
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": batch_data}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_batch_does_not_accept_dataset_id(self, client, post_json_admin_header, repository):
        """Test that batch PR creation refuses fields it does not know, dataset_id among them"""
        batch_data = [pr_body(1, dataset_id=999)]
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": batch_data}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert PullRequestTrigger.query.count() == 0

    def test_batch_triggers_belong_to_the_assignment_in_the_url(self, client, post_json_admin_header, repository):
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": [pr_body(1)]}), headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert response.json[0]["project_trigger_repository_id"] == repository.id

    def test_batch_not_found_repository(self, client, post_json_admin_header):
        """Test that batch PR creation fails if repository doesn't exist"""
        batch_data = [pr_body(1)]
        response = client.post(
            "/projects/1/trigger_repositories/9999/pull_requests/batch",
            data=json.dumps({"pull_requests": batch_data}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_batch_pull_requests_not_list(self, client, post_json_admin_header, repository):
        """Test that batch PR creation fails if pull_requests is not a list"""
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": {"number": 1, "title": "PR"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "must be a list" in response.json.get("error", "")


class TestPullRequestBatchBehaviour:
    def post(self, client, headers, repository, body):
        return client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
            data=json.dumps({"pull_requests": body}), headers=headers
        )

    def test_new_pull_requests_are_unknown(self, client, post_json_admin_header, repository):
        response = self.post(client, post_json_admin_header, repository, [pr_body()])
        assert response.status_code == 201
        assert response.json[0]["state"] == "UNKNOWN"
        assert response.json[0]["state_cause"] is None
        assert response.json[0]["task_id"] is None

    def test_exactly_100_is_accepted(self, client, post_json_admin_header, repository):
        response = self.post(client, post_json_admin_header, repository, [pr_body(n) for n in range(1, 101)])
        assert response.status_code == 201
        assert len(response.json) == 100

    def test_duplicate_number_in_a_batch_is_stored_once(self, client, post_json_admin_header, repository):
        response = self.post(client, post_json_admin_header, repository, [pr_body(1), pr_body(1)])
        assert response.status_code == 201
        assert PullRequestTrigger.query.count() == 1

    def test_number_already_ingested_is_left_as_it_is(self, client, post_json_admin_header, repository):
        assert self.post(client, post_json_admin_header, repository, [pr_body(1)]).status_code == 201
        response = self.post(client, post_json_admin_header, repository, [pr_body(1, title="changed")])
        assert response.status_code == 201
        assert [pr["title"] for pr in response.json] == ["PR 1"]
        assert PullRequestTrigger.query.count() == 1

    @pytest.mark.parametrize("field", [
        "number", "title", "raised_by", "merged_at", "merge_commit_sha", "base_branch", "files_truncated",
        "changed_files",
    ])
    def test_each_required_field(self, client, post_json_admin_header, repository, field):
        body = pr_body()
        del body[field]
        response = self.post(client, post_json_admin_header, repository, [body])
        assert response.status_code == 400
        assert field in response.json["error"]
        assert PullRequestTrigger.query.count() == 0

    def test_invalid_merged_at(self, client, post_json_admin_header, repository):
        response = self.post(client, post_json_admin_header, repository, [pr_body(merged_at="yesterday")])
        assert response.status_code == 400

    def test_merged_at_with_an_offset_is_stored_as_utc(self, client, post_json_admin_header, repository):
        response = self.post(
            client, post_json_admin_header, repository, [pr_body(merged_at="2026-01-01T10:00:00+01:00")]
        )
        assert response.status_code == 201, response.json
        assert PullRequestTrigger.query.one().merged_at.isoformat() == "2026-01-01T09:00:00"

    def test_the_project_comes_from_the_assignment(self, client, post_json_admin_header, repository):
        self.post(client, post_json_admin_header, repository, [pr_body()])
        assert PullRequestTrigger.query.one().project_id == repository.project_id


@pytest.fixture
def pull_request(client, post_json_admin_header, repository):
    response = client.post(
        f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/batch",
        data=json.dumps({"pull_requests": [pr_body(1, title="A PR", raised_by="user1", merge_commit_sha="a" * 40)]}),
        headers=post_json_admin_header
    )
    assert response.status_code == 201
    return response.json[0]


class TestPatchPullRequest:
    def url(self, repository, pull_request):
        return f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}"

    def patch(self, client, headers, repository, pull_request, body):
        return client.patch(self.url(repository, pull_request), data=json.dumps(body), headers=headers)

    @pytest.mark.parametrize("state", ["IGNORED", "REJECTED"])
    def test_state_with_reason(self, client, post_json_admin_header, repository, pull_request, state):
        response = self.patch(
            client, post_json_admin_header, repository, pull_request, {"state": state, "state_cause": "why"}
        )
        assert response.status_code == 200
        assert response.json["state"] == state
        assert response.json["state_cause"] == "why"

    @pytest.mark.parametrize("state", ["IGNORED", "REJECTED"])
    def test_ignored_and_rejected_need_a_reason(
        self, client, post_json_admin_header, repository, pull_request, state
    ):
        response = self.patch(client, post_json_admin_header, repository, pull_request, {"state": state})
        assert response.status_code == 400

    def test_reason_not_allowed_for_unknown(self, client, post_json_admin_header, repository, pull_request):
        response = self.patch(
            client, post_json_admin_header, repository, pull_request, {"state": "UNKNOWN", "state_cause": "why"}
        )
        assert response.status_code == 400

    @pytest.mark.parametrize("state", ["READY", "FAILURE", "unknown"])
    def test_invalid_state_fails(self, client, post_json_admin_header, repository, pull_request, state):
        response = self.patch(client, post_json_admin_header, repository, pull_request, {"state": state})
        assert response.status_code == 400


class TestListPullRequests:
    def test_filter_by_state(self, client, post_json_admin_header, simple_admin_header, repository, pull_request):
        url = f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests"
        assert client.get(f"{url}?state=UNKNOWN", headers=simple_admin_header).json["total"] == 1
        assert client.get(f"{url}?state=YIELDED", headers=simple_admin_header).json["items"] == []

    def test_filter_by_invalid_state_fails(self, client, simple_admin_header, repository):
        response = client.get(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests?state=SUCCESS", headers=simple_admin_header
        )
        assert response.status_code == 400

    def test_invalid_page_fails(self, client, simple_admin_header, repository):
        response = client.get(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests?page=x", headers=simple_admin_header
        )
        assert response.status_code == 400


def spec_file(**spec) -> str:
    return json.dumps({"spec": spec})


class TestPostPullRequestTask:
    def url(self, repository, pull_request):
        return f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/{pull_request['number']}/task"

    def post(self, client, headers, repository, pull_request, spec_raw):
        return client.post(
            self.url(repository, pull_request), data=json.dumps({"spec_raw": spec_raw}), headers=headers
        )

    def get_pr(self, repository, pull_request):
        return PullRequestTrigger.query.join(PullRequest).filter(
            PullRequestTrigger.project_trigger_repository_id == repository.id, PullRequest.number == pull_request["number"]
        ).one()

    def test_create(self, client, post_json_admin_header, repository, pull_request, default_dataset):
        spec_raw = spec_file(image="example:latest", env={"KEY": "value"})
        response = self.post(client, post_json_admin_header, repository, pull_request, spec_raw)
        assert response.status_code == 201
        assert response.json["status"] == "PENDING"
        assert response.json["attempt"] == 1
        assert response.json["project_id"] == repository.project_id
        # The task's spec is its own row, on the project's default dataset
        assert response.json["spec"] == {
            "image": "example:latest", "dataset_id": default_dataset.id, "env": {"KEY": "value"}
        }
        pr = self.get_pr(repository, pull_request)
        assert pr.state == "YIELDED"
        assert pr.spec_raw == spec_raw
        assert pr.task.id == response.json["id"]
        assert response.json["trigger_id"] == pr.id
        spec = TaskSpec.query.one()
        assert (spec.image, spec.dataset_id, spec.env) == ("example:latest", default_dataset.id, {"KEY": "value"})
        assert pr.task.task_spec_id == spec.id

    def test_create_twice_is_idempotent(self, client, post_json_admin_header, repository, pull_request):
        spec_raw = spec_file(image="example:latest")
        first = self.post(client, post_json_admin_header, repository, pull_request, spec_raw)
        second = self.post(client, post_json_admin_header, repository, pull_request, spec_raw)
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json["id"] == first.json["id"]
        assert Task.query.filter_by(trigger_id=self.get_pr(repository, pull_request).id).count() == 1
        assert TaskSpec.query.count() == 1

    def test_a_spec_without_a_dataset_is_valid(self, client, post_json_admin_header, repository, pull_request):
        repository.project.default_dataset_id = None
        response = self.post(
            client, post_json_admin_header, repository, pull_request, spec_file(image="example:latest")
        )
        assert response.status_code == 201
        assert response.json["spec"]["dataset_id"] is None

    @pytest.mark.parametrize("body", [{}, {"spec_raw": None}, {"spec_raw": {"image": "x"}}, {"spec_raw": []}])
    def test_invalid_body_fails(self, client, post_json_admin_header, repository, pull_request, body):
        response = client.post(
            self.url(repository, pull_request), data=json.dumps(body), headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert self.get_pr(repository, pull_request).state == "UNKNOWN"

    @pytest.mark.parametrize("spec_raw", [
        "not json",
        "{}",
        spec_file(),
        spec_file(env={"A": "b"}),
        spec_file(image="example:latest", unknown_field=1),
        spec_file(image="example:latest", env="not-a-dict"),
        spec_file(image="a" * 257),
        spec_file(image="example:latest", env={"1BAD": "x"}),
        spec_file(image="example:latest", env={"CDM_SCHEMA": "x"}),
        spec_file(image="example:latest", env={"WRITE_SCHEMA": "x"}),
        spec_file(image="example:latest", env={"K": "v" * TASK_ENV_MAX_BYTES}),
    ])
    def test_invalid_spec_rejects_the_pr_and_keeps_the_spec(
        self, client, post_json_admin_header, repository, pull_request, spec_raw
    ):
        response = self.post(client, post_json_admin_header, repository, pull_request, spec_raw)
        assert response.status_code == 400
        pr = self.get_pr(repository, pull_request)
        assert pr.state == "REJECTED"
        assert pr.state_cause == response.json["error"][:1024]
        assert pr.spec_raw == spec_raw
        assert Task.query.count() == 0
        assert TaskSpec.query.count() == 0

    def test_spec_over_the_cap_rejects_the_pr_without_keeping_it(
        self, client, post_json_admin_header, repository, pull_request
    ):
        padding = SPEC_RAW_MAX_BYTES - len(spec_file(image="example:latest", params={"p": ""}).encode())
        at_cap = spec_file(image="example:latest", params={"p": "x" * padding})
        assert len(at_cap.encode()) == SPEC_RAW_MAX_BYTES

        response = self.post(client, post_json_admin_header, repository, pull_request, at_cap + " ")
        assert response.status_code == 400
        assert "limit" in response.json["error"]
        pr = self.get_pr(repository, pull_request)
        assert pr.state == "REJECTED"
        assert pr.spec_raw is None
        assert Task.query.count() == 0

    def test_spec_at_the_cap_is_accepted(self, client, post_json_admin_header, repository, pull_request):
        padding = SPEC_RAW_MAX_BYTES - len(spec_file(image="example:latest", params={"p": ""}).encode())
        at_cap = spec_file(image="example:latest", params={"p": "x" * padding})
        response = self.post(client, post_json_admin_header, repository, pull_request, at_cap)
        assert response.status_code == 201
        assert self.get_pr(repository, pull_request).spec_raw == at_cap

    def default_dataset_override_in_other_project_fails(
            self, client, post_json_admin_header, repository, pull_request, other_project, user_uuid
        ):
        other_secret = Secret(label="other-test-creds", provider=SecretProviderType.K8S)
        other_secret.add()
        other_ds = Dataset(
            name="OtherDs", host="example.com", port=5432, secret_id=other_secret.id
        )
        other_ds.add(user_id=user_uuid)
        ProjectDataset(other_project.id, other_ds.id).add()
        spec_raw = spec_file(image="example:latest", dataset=other_ds.name)
        response = self.post(client, post_json_admin_header, repository, pull_request, spec_raw)
        assert response.status_code == 400
        assert "does not belong to project" in response.json["error"]
        assert Task.query.count() == 0
        pr = self.get_pr(repository, pull_request)
        assert pr.state == "REJECTED"
        assert pr.spec_raw == spec_raw

    def test_pull_request_not_found(self, client, post_json_admin_header, repository):
        response = client.post(
            f"/projects/{repository.project_id}/trigger_repositories/{repository.id}/pull_requests/999/task",
            data=json.dumps({"spec_raw": ""}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_requires_auth(self, client, repository, pull_request):
        response = client.post(
            self.url(repository, pull_request),
            data=json.dumps({"spec_raw": ""}),
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401


class TestPullRequestTriggerDTO:
    def test_fields(self, pull_request):
        """Dagster's PullRequestTrigger wire model requires these"""
        expected_fields = ['project_id', 'project_trigger_repository_id', 'number', 'title', 'raised_by', 'merged_at',
                           'merge_commit_sha', 'state', 'state_cause', 'task_id']
        assert set(pull_request) == set(expected_fields)

    def test_values(self, repository, pull_request):
        assert pull_request["project_trigger_repository_id"] == repository.id
        assert pull_request["state"] == "UNKNOWN"
        assert pull_request["state_cause"] is None
        assert pull_request["task_id"] is None

    def test_merged_at_is_iso_string(self, pull_request):
        assert pull_request["merged_at"] == "2026-01-01T10:00:00"
