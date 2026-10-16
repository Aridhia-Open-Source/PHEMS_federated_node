import pytest
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.dtos.results_repository import ProjectResultsRepositoryDTO, ResultsRepositoryDTO
from app.helpers.exceptions import InvalidRequest
from app.helpers.repository_loop import check_no_loop, normalise_dir
from app.models.project import Project
from app.models.project_results_repository import ProjectResultsRepository
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository

# What a repository needs to say about its git host. The secret is the conftest secret.
REPO_FIELDS = {"provider": "github", "api_uri": "https://api.github.com", "secret_label": "test-creds"}


@pytest.fixture
def results_post_body(secret):
    return {**REPO_FIELDS, "uri": "github.com/org/results"}


def make_trigger(project, secret, uri="github.com/org/results", watch_dir="triggers"):
    repo = TriggerRepository(
        uri=uri, provider="github", api_uri="https://api.github.com",
        secret_id=secret.id, watch_dir=watch_dir, project_id=project.id
    )
    repo.add()
    return repo


class TestGetResultsRepositories:
    def test_list_empty(self, client, simple_admin_header):
        response = client.get("/results_repositories/", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_is_global(self, client, simple_admin_header, results_repo, results_assignment):
        response = client.get("/results_repositories", headers=simple_admin_header)
        assert [r["id"] for r in response.json] == [results_repo.id]
        assert set(response.json[0]) == {"id", "uri", "provider", "api_uri", "secret"}

    def test_get_by_id(self, client, simple_admin_header, results_repo):
        response = client.get(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == ResultsRepositoryDTO.from_model(results_repo).dump()
        assert response.json["secret"]["label"] == "test-creds"

    def test_get_by_id_not_found(self, client, simple_admin_header):
        response = client.get("/results_repositories/9999", headers=simple_admin_header)
        assert response.status_code == 404


class TestPostResultsRepository:
    def test_create(self, client, post_json_admin_header, results_post_body):
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/results"
        assert set(response.json) == {"id", "uri", "provider", "api_uri", "secret"}
        assert ResultsRepository.query.count() == 1
        assert ProjectResultsRepository.query.count() == 0

    def test_only_an_admin_writes(self, client, post_json_user_header, results_post_body, results_repo, mock_kc_client):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.side_effect = (
            lambda token, scope, *args, **kwargs: scope != 'can_do_admin'
        )
        url = f"/results_repositories/{results_repo.id}"
        body = {**results_post_body, "uri": "github.com/org/another"}
        assert client.post("/results_repositories", json=body, headers=post_json_user_header).status_code == 403
        assert client.patch(url, json={"provider": "gitea"}, headers=post_json_user_header).status_code == 403
        assert client.delete(url, headers=post_json_user_header).status_code == 403
        assert ResultsRepository.query.count() == 1

    @pytest.mark.parametrize("field", ["project_id", "target_dir"])
    def test_create_rejects_assignment_fields(self, client, post_json_admin_header, results_post_body, field):
        response = client.post(
            "/results_repositories", json={**results_post_body, field: 1}, headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert ResultsRepository.query.count() == 0

    def test_create_normalises_uri(self, client, post_json_admin_header, results_post_body):
        body = {**results_post_body, "uri": "https://GitHub.com/org/results/"}
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/results"

    def test_create_strips_the_git_suffix(self, client, post_json_admin_header, results_post_body):
        body = {**results_post_body, "uri": "https://github.com/org/results.git"}
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["uri"] == "github.com/org/results"

    @pytest.mark.parametrize("uri", ["github.com/org", "ssh://github.com/org/results"])
    def test_create_rejects_an_unparsable_uri(self, client, post_json_admin_header, results_post_body, uri):
        response = client.post("/results_repositories", json={**results_post_body, "uri": uri}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "Invalid repository uri" in response.json["error"]
        assert ResultsRepository.query.count() == 0

    def test_create_defaults_the_api_uri(self, client, post_json_admin_header, results_post_body):
        del results_post_body["api_uri"]
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["api_uri"] == "https://api.github.com"

    def test_create_defaults_the_gitea_api_uri_to_the_repository_host(self, client, post_json_admin_header, results_post_body):
        body = {**results_post_body, "provider": "gitea", "uri": "gitea.fn.svc:4000/org/results"}
        del body["api_uri"]
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["api_uri"] == "https://gitea.fn.svc:4000/api/v1"

    def test_create_keeps_a_given_api_uri(self, client, post_json_admin_header, results_post_body):
        body = {
            **results_post_body, "provider": "gitea", "uri": "http://gitea.fn.svc:4000/org/results",
            "api_uri": "http://gitea.fn.svc:4000/api/v1"
        }
        response = client.post("/results_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["api_uri"] == "http://gitea.fn.svc:4000/api/v1"

    @pytest.mark.parametrize("api_uri", [
        "ftp://api.github.com", "https://user:pass@api.github.com", "https://evil.example.com/api", "https://github.com"
    ])
    def test_create_rejects_an_api_uri_not_on_the_repository_host(self, client, post_json_admin_header, results_post_body, api_uri):
        response = client.post("/results_repositories", json={**results_post_body, "api_uri": api_uri}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "api_uri" in response.json["error"]
        assert ResultsRepository.query.count() == 0

    @pytest.mark.parametrize("field", ["uri", "provider", "secret_label"])
    def test_create_requires_field(self, client, post_json_admin_header, results_post_body, field):
        del results_post_body[field]
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert field in response.json["error"]

    def test_the_same_uri_twice_is_a_conflict(self, client, post_json_admin_header, results_repo, results_post_body):
        response = client.post("/results_repositories", json=results_post_body, headers=post_json_admin_header)
        assert response.status_code == 409
        assert ResultsRepository.query.count() == 1

    def test_create_with_unknown_secret_fails(self, client, post_json_admin_header, results_post_body):
        response = client.post(
            "/results_repositories", json={**results_post_body, "secret_label": "nope"}, headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_create_with_unknown_provider_fails(self, client, post_json_admin_header, results_post_body):
        response = client.post(
            "/results_repositories", json={**results_post_body, "provider": "svn"}, headers=post_json_admin_header
        )
        assert response.status_code == 400


class TestPatchResultsRepository:
    def test_update_fields(self, client, post_json_admin_header, results_repo):
        response = client.patch(
            f"/results_repositories/{results_repo.id}", json={"api_uri": "https://api.github.com/v3"},
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["api_uri"] == "https://api.github.com/v3"

    @pytest.mark.parametrize("api_uri", [
        "ftp://api.github.com", "https://user:pass@api.github.com", "https://evil.example.com/api", "https://github.com"
    ])
    def test_update_rejects_an_api_uri_not_on_the_repository_host(self, client, post_json_admin_header, results_repo, api_uri):
        response = client.patch(f"/results_repositories/{results_repo.id}", json={"api_uri": api_uri}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "api_uri" in response.json["error"]
        assert results_repo.api_uri == "https://api.github.com"

    @pytest.mark.parametrize("field", ["target_dir", "project_id", "uri"])
    def test_assignment_fields_and_uri_are_not_updatable(self, client, post_json_admin_header, results_repo, field):
        response = client.patch(f"/results_repositories/{results_repo.id}", json={field: "x"}, headers=post_json_admin_header)
        assert response.status_code == 400

    def test_empty_body(self, client, post_json_admin_header, results_repo):
        response = client.patch(f"/results_repositories/{results_repo.id}", json={}, headers=post_json_admin_header)
        assert response.status_code == 400

    def test_not_found(self, client, post_json_admin_header):
        response = client.patch("/results_repositories/9999", json={"provider": "gitea"}, headers=post_json_admin_header)
        assert response.status_code == 404

    def test_unassigned_repository_needs_no_lock(self, client, post_json_admin_header, results_repo):
        response = client.patch(f"/results_repositories/{results_repo.id}", json={"provider": "gitea"}, headers=post_json_admin_header)
        assert response.status_code == 200

    def test_edit_needs_every_assigned_project_drained(
        self, client, post_json_admin_header, results_repo, results_assignment, project, other_project
    ):
        ProjectResultsRepository(other_project.id, results_repo.id, target_dir="out").add()
        project.locked = True
        other_project.locked = False
        db.session.commit()
        url = f"/results_repositories/{results_repo.id}"
        response = client.patch(url, json={"provider": "gitea"}, headers=post_json_admin_header)
        assert response.status_code == 409
        assert ResultsRepository.get_by_id(results_repo.id).provider == "github"

        other_project.locked = True
        db.session.commit()
        response = client.patch(url, json={"provider": "gitea"}, headers=post_json_admin_header)
        assert response.status_code == 200

    def test_secret_rotation_alone_is_exempt(
        self, client, post_json_admin_header, results_repo, results_assignment, project, make_task, secret
    ):
        make_task(project=project, status="RUNNING")
        response = client.patch(
            f"/results_repositories/{results_repo.id}", json={"secret_label": secret.label}, headers=post_json_admin_header
        )
        assert response.status_code == 200


class TestDeleteResultsRepository:
    def test_delete_unassigned(self, client, simple_admin_header, results_repo):
        response = client.delete(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert ResultsRepository.query.count() == 0

    def test_delete_removes_the_assignments(self, client, simple_admin_header, results_repo, results_assignment, lock_project):
        response = client.delete(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert ResultsRepository.query.count() == 0
        assert ProjectResultsRepository.query.count() == 0

    def test_delete_needs_the_assigned_projects_locked(self, client, simple_admin_header, results_repo, results_assignment):
        response = client.delete(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == 409
        assert ResultsRepository.query.count() == 1

    def test_secret_in_use_cannot_be_deleted(self, client, simple_admin_header, results_repo, secret):
        response = client.delete(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 409

    def test_database_rejects_a_second_assignment_in_a_project(self, results_repo, results_assignment, secret):
        other = ResultsRepository(
            uri="github.com/org/another", provider="github", api_uri="https://api.github.com", secret_id=secret.id
        )
        other.add()
        with pytest.raises(IntegrityError):
            ProjectResultsRepository(results_assignment.project_id, other.id, target_dir="x").add()


class TestProjectResultsRepositories:
    """/projects/<id>/results_repositories"""

    def url(self, project, *rest):
        return "/".join([f"/projects/{project.id}/results_repositories", *map(str, rest)])

    def test_list_empty(self, client, simple_admin_header, project):
        assert client.get(self.url(project), headers=simple_admin_header).json == []

    def test_list_returns_the_assignment_with_the_repository_nested(
        self, client, simple_admin_header, project, results_repo, results_assignment
    ):
        response = client.get(self.url(project), headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == [ProjectResultsRepositoryDTO.from_model(results_assignment).dump()]
        [item] = response.json
        assert (item["target_dir"], item["owned_by_federated_node"], item["active"]) == ("results", True, True)
        assert item["results_repository"]["id"] == results_repo.id

    def test_list_returns_an_inactive_assignment_with_flags(
        self, client, simple_admin_header, project, results_assignment
    ):
        results_assignment.revoked = True
        db.session.commit()
        [item] = client.get(self.url(project), headers=simple_admin_header).json
        assert (item["enabled"], item["revoked"], item["active"]) == (True, True, False)

    def test_list_is_the_projects_own(self, client, simple_admin_header, other_project, results_assignment):
        assert client.get(self.url(other_project), headers=simple_admin_header).json == []

    def test_get_by_assignment_id(self, client, simple_admin_header, project, results_assignment, other_project):
        assert client.get(self.url(project, results_assignment.id), headers=simple_admin_header).status_code == 200
        assert client.get(self.url(other_project, results_assignment.id), headers=simple_admin_header).status_code == 404

    @pytest.mark.usefixtures("lock_project")
    def test_assign(self, client, post_json_admin_header, project, results_repo):
        body = {"results_repository_id": results_repo.id, "target_dir": "./a//b/", "owned_by_federated_node": False}
        response = client.post(self.url(project), json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert (response.json["target_dir"], response.json["owned_by_federated_node"]) == ("a/b", False)
        assert (response.json["enabled"], response.json["revoked"]) == (True, False)
        assert project.get_results_repository().results_repository == results_repo

    @pytest.mark.usefixtures("lock_project")
    @pytest.mark.parametrize("missing", ["results_repository_id", "target_dir"])
    def test_assign_requires_field(self, client, post_json_admin_header, project, results_repo, missing):
        body = {"results_repository_id": results_repo.id, "target_dir": "results"}
        del body[missing]
        assert client.post(self.url(project), json=body, headers=post_json_admin_header).status_code == 400

    @pytest.mark.usefixtures("lock_project")
    @pytest.mark.parametrize("target_dir", ["tmp/../results", "..", ".", "/"])
    def test_assign_refuses_bad_directories(self, client, post_json_admin_header, project, results_repo, target_dir):
        body = {"results_repository_id": results_repo.id, "target_dir": target_dir}
        assert client.post(self.url(project), json=body, headers=post_json_admin_header).status_code == 400
        assert ProjectResultsRepository.query.count() == 0

    @pytest.mark.usefixtures("lock_project")
    def test_assign_unknown_repository(self, client, post_json_admin_header, project):
        body = {"results_repository_id": 9999, "target_dir": "results"}
        assert client.post(self.url(project), json=body, headers=post_json_admin_header).status_code == 404

    @pytest.mark.usefixtures("lock_project")
    def test_second_assignment_in_a_project_is_a_conflict(
        self, client, post_json_admin_header, project, results_repo, results_assignment, secret
    ):
        another = ResultsRepository(
            uri="github.com/org/another", provider="github", api_uri="https://api.github.com", secret_id=secret.id
        )
        another.add()
        body = {"results_repository_id": another.id, "target_dir": "results"}
        response = client.post(self.url(project), json=body, headers=post_json_admin_header)
        assert response.status_code == 409
        assert ProjectResultsRepository.query.count() == 1

    def test_another_project_can_use_the_same_repository(
        self, client, post_json_admin_header, results_repo, results_assignment, other_project
    ):
        other_project.locked = True
        db.session.commit()
        body = {"results_repository_id": results_repo.id, "target_dir": "other"}
        response = client.post(self.url(other_project), json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert ProjectResultsRepository.query.count() == 2

    def test_patch_the_directory(self, client, post_json_admin_header, project, results_assignment, lock_project):
        response = client.patch(self.url(project, results_assignment.id), json={"target_dir": "./out/"}, headers=post_json_admin_header)
        assert response.status_code == 200
        assert response.json["target_dir"] == "out"
        response = client.patch(self.url(project, results_assignment.id), json={"target_dir": "out/../x"}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert ProjectResultsRepository.get_by_id(results_assignment.id).target_dir == "out"

    def test_patch_empty_directory(self, client, post_json_admin_header, project, results_assignment, lock_project):
        response = client.patch(self.url(project, results_assignment.id), json={"target_dir": ""}, headers=post_json_admin_header)
        assert response.status_code == 400

    def test_patch_enabled_needs_the_lock(self, client, post_json_admin_header, project, results_assignment):
        response = client.patch(self.url(project, results_assignment.id), json={"enabled": False}, headers=post_json_admin_header)
        assert response.status_code == 409
        project.locked = True
        db.session.commit()
        response = client.patch(self.url(project, results_assignment.id), json={"enabled": False}, headers=post_json_admin_header)
        assert (response.json["enabled"], response.json["active"]) == (False, False)

    def test_revoke_is_immediate_and_leaves_enabled(self, client, post_json_admin_header, project, results_assignment, make_task):
        make_task(project=project)
        response = client.patch(self.url(project, results_assignment.id), json={"revoked": True}, headers=post_json_admin_header)
        assert response.status_code == 200
        assert (response.json["enabled"], response.json["revoked"], response.json["active"]) == (True, True, False)
        response = client.patch(self.url(project, results_assignment.id), json={"revoked": False}, headers=post_json_admin_header)
        assert response.json["active"] is True

    @pytest.mark.parametrize("body", [{}, {"project_id": 2}, {"results_repository_id": 2}, {"enabled": "yes"}])
    def test_patch_rejects_other_fields(self, client, post_json_admin_header, project, results_assignment, lock_project, body):
        response = client.patch(self.url(project, results_assignment.id), json=body, headers=post_json_admin_header)
        assert response.status_code == 400

    def test_unassign_keeps_the_repository(self, client, post_json_admin_header, project, results_assignment, lock_project):
        response = client.delete(self.url(project, results_assignment.id), headers=post_json_admin_header)
        assert response.status_code == 204
        assert ProjectResultsRepository.query.count() == 0
        assert ResultsRepository.query.count() == 1
        assert project.get_results_repository() is None

    def test_unassign_needs_the_lock(self, client, post_json_admin_header, project, results_assignment):
        response = client.delete(self.url(project, results_assignment.id), headers=post_json_admin_header)
        assert response.status_code == 409

    def test_project_reaches_its_assignment_through_one_accessor(self, project, results_assignment):
        assert Project.get_by_id(project.id).get_results_repository() == results_assignment

    def test_project_without_assignment(self, project):
        assert project.get_results_repository() is None

    def test_delete_project_removes_the_assignment_only(
        self, client, post_json_admin_header, project, results_repo, results_assignment, lock_project
    ):
        assert client.delete(f"/projects/{project.id}", headers=post_json_admin_header).status_code == 204
        assert ProjectResultsRepository.query.count() == 0
        assert ResultsRepository.query.count() == 1


@pytest.mark.usefixtures("lock_project")
class TestLoopGuard:
    """A results assignment and a trigger repository that are the same repository must not overlap."""

    def assign(self, client, header, project, repo, **changes):
        body = {"results_repository_id": repo.id, "target_dir": "results", **changes}
        return client.post(f"/projects/{project.id}/results_repositories", json=body, headers=header)

    def create_trigger(self, client, header, project, **changes):
        body = {**REPO_FIELDS, "uri": "github.com/org/results", "project_id": project.id, "watch_dir": "triggers", **changes}
        return client.post("/trigger_repositories", json=body, headers=header)

    @pytest.mark.parametrize("watch_dir,target_dir,ok", [
        ("triggers", "results", True),
        ("triggers", "triggers", False),
        ("triggers", "triggers/out", False),
        ("triggers/in", "triggers", False),
        ("triggers", "triggers-out", True),
        ("a/b", "a/c", True),
        ("/triggers/", "triggers", False),
        ("", "results", False),
    ])
    def test_assigned_after_trigger(self, client, post_json_admin_header, project, secret, results_repo, watch_dir, target_dir, ok):
        make_trigger(project, secret, watch_dir=watch_dir)
        response = self.assign(client, post_json_admin_header, project, results_repo, target_dir=target_dir)
        assert (response.status_code == 201) is ok
        assert ProjectResultsRepository.query.count() == (1 if ok else 0)

    @pytest.mark.parametrize("watch_dir,ok", [
        ("triggers", True),
        ("results", False),
        ("results/in", False),
        ("res", True),
        ("", False),
    ])
    def test_trigger_created_after_assignment(self, client, post_json_admin_header, project, results_assignment, watch_dir, ok):
        response = self.create_trigger(client, post_json_admin_header, project, watch_dir=watch_dir)
        assert (response.status_code == 201) is ok
        assert TriggerRepository.query.count() == (1 if ok else 0)

    def test_trigger_without_watch_dir_is_refused_with_a_clear_message(self, client, post_json_admin_header, project, results_assignment):
        body = {**REPO_FIELDS, "uri": "github.com/org/results", "project_id": project.id}
        response = client.post("/trigger_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert "whole repository" in response.json["error"]

    def test_different_remotes_are_fine(self, client, post_json_admin_header, project, results_assignment):
        response = self.create_trigger(client, post_json_admin_header, project, uri="github.com/org/elsewhere", watch_dir="results")
        assert response.status_code == 201

    def test_a_trigger_in_another_project_is_refused_too(self, client, post_json_admin_header, results_assignment, other_project):
        response = self.create_trigger(client, post_json_admin_header, other_project, watch_dir="results")
        assert response.status_code == 400
        assert TriggerRepository.query.count() == 0

    def test_a_trigger_in_another_project_on_a_clear_directory_is_fine(
        self, client, post_json_admin_header, results_assignment, other_project
    ):
        response = self.create_trigger(client, post_json_admin_header, other_project, watch_dir="elsewhere")
        assert response.status_code == 201

    def test_an_assignment_overlapping_another_projects_trigger_is_refused(
        self, client, post_json_admin_header, secret, results_repo, other_project, project
    ):
        make_trigger(other_project, secret, watch_dir="results")
        response = self.assign(client, post_json_admin_header, project, results_repo)
        assert response.status_code == 400
        assert ProjectResultsRepository.query.count() == 0

    def test_patching_watch_dir_into_the_results_dir_is_refused(self, client, post_json_admin_header, project, secret, results_assignment):
        trigger = make_trigger(project, secret, watch_dir="triggers")
        response = client.patch(f"/trigger_repositories/{trigger.id}", json={"watch_dir": "results/x"}, headers=post_json_admin_header)
        assert response.status_code == 400
        assert TriggerRepository.get_by_id(trigger.id).watch_dir == "triggers"

    def test_patching_target_dir_into_the_watch_dir_is_refused(self, client, post_json_admin_header, project, secret, results_assignment):
        make_trigger(project, secret, watch_dir="triggers")
        response = client.patch(
            f"/projects/{project.id}/results_repositories/{results_assignment.id}", json={"target_dir": "triggers"},
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert ProjectResultsRepository.get_by_id(results_assignment.id).target_dir == "results"

    def test_patching_to_a_clear_directory_is_fine(self, client, post_json_admin_header, project, secret, results_assignment):
        make_trigger(project, secret, watch_dir="triggers")
        response = client.patch(
            f"/projects/{project.id}/results_repositories/{results_assignment.id}", json={"target_dir": "out"},
            headers=post_json_admin_header
        )
        assert response.status_code == 200


@pytest.mark.usefixtures("lock_project")
class TestDirectoryNormalisation:
    @pytest.mark.parametrize("directory,expected", [
        ("results", "results"),
        ("/results/", "results"),
        ("./results", "results"),
        ("a//b/./c/", "a/b/c"),
        (".", ""),
        ("", ""),
    ])
    def test_normalise_dir(self, directory, expected):
        assert normalise_dir(directory) == expected

    @pytest.mark.parametrize("directory", ["../results", "tmp/../results", "a/.."])
    def test_normalise_dir_refuses_parent_segments(self, directory):
        with pytest.raises(InvalidRequest):
            normalise_dir(directory)

    def test_loop_guard_compares_normalised_directories(self, project, secret, results_assignment):
        make_trigger(project, secret, watch_dir="./results/")
        with pytest.raises(InvalidRequest):
            check_no_loop("github.com/org/results")

    def test_trigger_create_and_patch(self, client, post_json_admin_header, project, secret):
        body = {**REPO_FIELDS, "uri": "github.com/org/other", "project_id": project.id, "watch_dir": "./t//"}
        response = client.post("/trigger_repositories", json=body, headers=post_json_admin_header)
        assert response.status_code == 201
        assert response.json["watch_dir"] == "t"
        url = f"/trigger_repositories/{response.json['id']}"
        assert client.patch(url, json={"watch_dir": "/u/./v"}, headers=post_json_admin_header).json["watch_dir"] == "u/v"
        assert client.patch(url, json={"watch_dir": "u/../v"}, headers=post_json_admin_header).status_code == 400
        assert client.post("/trigger_repositories", json={**body, "uri": "github.com/org/third", "watch_dir": "../t"}, headers=post_json_admin_header).status_code == 400
