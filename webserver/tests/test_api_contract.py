"""
The API contract Dagster and fncli consume, pinned before ADR 0019 changes it.

Every test asserts the exact key set and the types of what an endpoint returns, not only its
status. The response bodies are also written to JSON files in tests/contracts/ (normalised: the
timestamps the database sets are fixed). A normal run compares each body with its committed
copy, so any change to a response fails here until the copy is regenerated on purpose:

    ./run_tests.sh ci "tests/test_api_contract.py --regenerate-contracts"

Dagster (dagster/app/tests/test_contract_fixtures.py) and fncli (scripts/fncli/tests/
test_contract_fixtures.py) parse the same files into their models. Dagster's test image can
only see dagster/, so scripts/sync_contract_fixtures.sh copies them there.

Endpoints whose shape stays the same under ADR 0019 are pinned as they are. Those that change
are pinned as they are today and, separately, as they will be: the second test is
xfail(strict=True) naming the stage that flips it, so that stage has to remove the marker.
"""
import json
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.helpers.base_model import db
from app.models.dataset import Dataset
from app.models.project_dataset import ProjectDataset
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *
from tests.helpers.pull_requests import pr_body

CONTRACTS_DIR = Path(__file__).parent / "contracts"
FIXED_WIRE_DATETIME = "2026-01-01 00:00:00"
NONE = type(None)

SECRET = {
    "id": int, "label": str, "description": (str, NONE), "provider": str,
    "key": str, "namespace": (str, NONE), "created_at": str, "updated_at": str,
}
TRIGGER_REPOSITORY = {"id": int, "uri": str, "provider": str, "api_uri": str, "secret": SECRET, "pr_cursor": (str, NONE)}
PROJECT_TRIGGER_REPOSITORY = {
    "id": int, "project_id": int, "trigger_repository": TRIGGER_REPOSITORY, "watch_dir": str,
    "base_branch": str, "dataset_id": (int, NONE), "initial_cursor": (str, NONE), "pr_cursor": str,
    "pr_count": int, "enabled": bool, "revoked": bool, "active": bool,
}
RESULTS_REPOSITORY = {"id": int, "uri": str, "provider": str, "api_uri": str, "secret": SECRET}
PROJECT_RESULTS_REPOSITORY = {
    "id": int, "project_id": int, "results_repository": RESULTS_REPOSITORY, "target_dir": str,
    "owned_by_federated_node": bool, "enabled": bool, "revoked": bool, "active": bool,
}
DATASET = {
    "id": int, "secret": SECRET, "name": str, "host": str, "port": int,
    "read_schema": (str, NONE), "write_schema": (str, NONE), "type": str,
    "extra_connection_args": (str, NONE), "created_at": str, "updated_at": str, "slug": str, "url": str,
}
PROJECT_DATASET = {
    "id": int, "project_id": int, "dataset": DATASET, "enabled": bool, "revoked": bool, "active": bool,
}
PROJECT = {
    "id": int, "name": str, "description": (str, NONE), "enabled": bool, "locked": bool,
    "default_dataset_id": (int, NONE), "created_at": str, "updated_at": str,
}
PULL_REQUEST = {
    "project_id": int, "project_trigger_repository_id": int, "number": int, "title": str, "raised_by": str, "merged_at": (str, NONE),
    "merge_commit_sha": str, "state": str, "state_cause": (str, NONE), "task_id": (int, NONE),
}
TASK = {
    "id": int, "name": str, "spec": {"image": str, "dataset_id": (int, NONE), "env": dict}, "attempt": int,
    "status": (str, NONE), "created_at": str, "updated_at": str, "requested_by": str, "project_id": int,
    "trigger_id": int, "dagster_run_id": (str, NONE), "exit_code": (int, NONE), "state_cause": (str, NONE), "started_at": (str, NONE),
    "completed_at": (str, NONE),
}
NEW_API_TASK = {"id": int, "api_request_id": int, "status": str, "created_at": str}
RESULT = {
    "id": int, "type": str, "task_id": int, "project_id": int, "results_repository_id": int, "attempts": int,
    "error": (str, NONE), "created_at": str, "updated_at": str, "step": str, "state": str,
    "branch": (str, NONE), "commit_sha": (str, NONE), "number": (int, NONE), "url": (str, NONE),
    "merged_at": (str, NONE), "merge_commit_sha": (str, NONE),
}
HEALTH_CHECK = {"message": str, "status_code": (int, NONE), "latency_ms": (int, NONE)}
HEALTHCHECK = {
    "id": int, "name": str, "enabled": bool, "status": str,
    "results_repository": {
        "id": int, "uri": str, "owned_by_federated_node": bool, "target_dir": str, "status": str,
        "health_check": HEALTH_CHECK,
    },
    "trigger_repositories": [{
        "id": int, "uri": str, "provider": str, "pr_count": int, "status": str, "health_check": HEALTH_CHECK,
    }],
}
ERROR = {"error": str}
REPOSITORY_PULL_REQUEST = {
    "id": int, "trigger_repository_id": int, "number": int, "title": str, "raised_by": str, "merged_at": str,
    "merge_commit_sha": str, "base_branch": str, "files_truncated": bool,
}
REPOSITORY_PULL_REQUESTS_PAGE = {"items": [REPOSITORY_PULL_REQUEST], "page": int, "per_page": int, "total": int}
PULL_REQUESTS_PAGE = {"items": [PULL_REQUEST], "page": int, "per_page": int, "total": int}


def page_of(item: dict) -> dict:
    return {"items": [item], "page": int, "per_page": int, "total": int, "pages": int}


def assert_shape(body, shape, where="body"):
    """The exact keys, and for each the exact type (an int is not a bool). A list shape holds the shape of its items."""
    if isinstance(shape, list):
        assert isinstance(body, list), f"{where} is not a list"
        for i, item in enumerate(body):
            assert_shape(item, shape[0], f"{where}[{i}]")
    elif isinstance(shape, dict):
        assert isinstance(body, dict), f"{where} is not an object"
        assert set(body) == set(shape), (
            f"{where}: unexpected keys {sorted(set(body) - set(shape))}, missing keys {sorted(set(shape) - set(body))}"
        )
        for key, expected in shape.items():
            assert_shape(body[key], expected, f"{where}.{key}")
    else:
        allowed = shape if isinstance(shape, tuple) else (shape,)
        assert type(body) in allowed, f"{where} is {type(body).__name__}, expected {allowed}"


def normalised(body):
    """Without what the database or the clock sets, so that a body can be compared across runs."""
    if isinstance(body, list):
        return [normalised(item) for item in body]
    if isinstance(body, dict):
        return {
            key: (
                FIXED_WIRE_DATETIME if key in ("created_at", "updated_at") and isinstance(value, str)
                else 0 if key == "latency_ms" and isinstance(value, int)
                else normalised(value)
            )
            for key, value in body.items()
        }
    return body


@pytest.fixture
def contract(request):
    """Check a response body against its committed JSON file, or rewrite the file with --regenerate-contracts."""
    regenerate = request.config.getoption("--regenerate-contracts")

    def check(name: str, body):
        path = CONTRACTS_DIR / f"{name}.json"
        body = normalised(body)
        if regenerate:
            CONTRACTS_DIR.mkdir(exist_ok=True)
            path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        else:
            assert path.exists(), f"{path} is missing, run with --regenerate-contracts"
            assert json.loads(path.read_text()) == body, (
                f"{path.name} differs from the response, run with --regenerate-contracts if that is intended"
            )
    return check


@pytest.fixture
def repo(default_repo):
    """The project's trigger repository, with a fixed initial cursor."""
    default_repo.initial_cursor = "2026-01-01T00:00:00"
    db.session.commit()
    return default_repo


@pytest.fixture
def pull_requests(client, post_json_admin_header, repo):
    """Two merged pull requests, ingested through the repository's batch endpoint."""
    response = client.post(
        f"/trigger_repositories/{repo.trigger_repository_id}/pull_requests/batch",
        json={"pull_requests": [pr_body(1, "2026-01-01T10:00:00Z"), pr_body(2, "2026-03-05T11:30:00Z")]},
        headers=post_json_admin_header,
    )
    assert response.status_code == HTTPStatus.CREATED
    return response.json


def spec_file(**spec) -> str:
    return json.dumps({"spec": spec})


class TestTriggerRepositories:
    def test_global_list(self, client, simple_admin_header, repo, contract):
        response = client.get("/trigger_repositories", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [TRIGGER_REPOSITORY])
        assert [r["id"] for r in response.json] == [repo.trigger_repository_id]
        contract("trigger_repositories_list", response.json)

    def test_by_id(self, client, simple_admin_header, repo, contract):
        response = client.get(f"/trigger_repositories/{repo.trigger_repository_id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, TRIGGER_REPOSITORY)
        assert response.json["id"] == repo.trigger_repository_id
        contract("trigger_repository", response.json)

    def test_project_assignments(self, client, simple_admin_header, repo, contract):
        response = client.get(f"/projects/{repo.project_id}/trigger_repositories", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [PROJECT_TRIGGER_REPOSITORY])
        [assignment] = response.json
        assert assignment["id"] == repo.id
        assert assignment["trigger_repository"]["uri"] == repo.trigger_repository.uri
        assert (assignment["enabled"], assignment["revoked"], assignment["active"]) == (True, False, True)
        assert assignment["dataset_id"] == repo.project.default_dataset_id
        contract("project_trigger_repositories", response.json)

    def test_pr_cursor_is_the_initial_cursor_then_the_latest_merge(self, client, simple_admin_header, repo):
        url = f"/projects/{repo.project_id}/trigger_repositories/{repo.id}"
        body = client.get(url, headers=simple_admin_header).json
        assert (body["pr_cursor"], body["pr_count"]) == ("2026-01-01T00:00:00Z", 0)
        assert body["initial_cursor"] == "2026-01-01T00:00:00"

    def test_pr_cursor_after_pull_requests(self, client, simple_admin_header, repo, pull_requests):
        body = client.get(f"/projects/{repo.project_id}/trigger_repositories/{repo.id}", headers=simple_admin_header).json
        assert (body["pr_cursor"], body["pr_count"]) == ("2026-03-05T11:30:00Z", 2)
        assert body["initial_cursor"] == "2026-01-01T00:00:00"

    def test_the_active_assignments_of_every_project(self, client, simple_admin_header, repo, contract):
        response = client.get("/project_trigger_repositories?active=true", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [PROJECT_TRIGGER_REPOSITORY])
        assert [a["id"] for a in response.json] == [repo.id]
        contract("project_trigger_repositories_active", response.json)

    def test_an_inactive_assignment_is_still_listed_for_the_project(self, client, simple_admin_header, repo):
        repo.revoked = True
        db.session.commit()
        [assignment] = client.get(f"/projects/{repo.project_id}/trigger_repositories", headers=simple_admin_header).json
        assert (assignment["revoked"], assignment["active"]) == (True, False)
        assert client.get("/project_trigger_repositories?active=true", headers=simple_admin_header).json == []


class TestPullRequests:
    def test_batch_create(self, client, simple_admin_header, repo, pull_requests, contract):
        assert_shape(pull_requests, {"created": [int], "existing": [int]})
        assert pull_requests == {"created": [1, 2], "existing": []}
        contract("repository_pull_requests_batch", pull_requests)
        items = client.get(
            f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests", headers=simple_admin_header
        ).json["items"]
        assert {pr["project_trigger_repository_id"] for pr in items} == {repo.id}
        assert {(pr["state"], pr["state_cause"], pr["task_id"]) for pr in items} == {("UNKNOWN", None, None)}

    def test_list_is_paged_and_filtered_by_state(self, client, simple_admin_header, repo, pull_requests, contract):
        url = f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests"
        response = client.get(url, headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, PULL_REQUESTS_PAGE)
        assert (response.json["page"], response.json["per_page"], response.json["total"]) == (1, 20, 2)
        # Most recent merge first
        assert [pr["number"] for pr in response.json["items"]] == [2, 1]
        contract("pull_requests_page", response.json)

        second = client.get(f"{url}?per_page=1&page=2", headers=simple_admin_header)
        assert_shape(second.json, PULL_REQUESTS_PAGE)
        assert [pr["number"] for pr in second.json["items"]] == [1]
        assert second.json["total"] == 2

        assert client.get(f"{url}?state=UNKNOWN", headers=simple_admin_header).json["total"] == 2
        yielded = client.get(f"{url}?state=YIELDED", headers=simple_admin_header)
        assert (yielded.json["items"], yielded.json["total"]) == ([], 0)

        invalid = client.get(f"{url}?state=NOPE", headers=simple_admin_header)
        assert invalid.status_code == HTTPStatus.BAD_REQUEST
        assert_shape(invalid.json, ERROR)

    def test_get(self, client, simple_admin_header, repo, pull_requests, contract):
        response = client.get(f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, PULL_REQUEST)
        assert (response.json["number"], response.json["merged_at"]) == (1, "2026-01-01T10:00:00")
        contract("pull_request", response.json)

        missing = client.get(f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/99", headers=simple_admin_header)
        assert missing.status_code == HTTPStatus.NOT_FOUND
        assert_shape(missing.json, ERROR)

    def test_patch_state(self, client, post_json_admin_header, repo, pull_requests, contract):
        url = f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1"
        response = client.patch(url, json={"state": "IGNORED", "state_cause": "no spec file"}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, PULL_REQUEST)
        assert (response.json["state"], response.json["state_cause"]) == ("IGNORED", "no spec file")
        contract("pull_request_ignored", response.json)
        assert client.get(url, headers=post_json_admin_header).json["state"] == "IGNORED"

    def test_task_is_created_then_returned(self, client, post_json_admin_header, repo, pull_requests, contract):
        url = f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1/task"
        body = {"spec_raw": spec_file(image="example:latest", env={"KEY": "value"})}

        created = client.post(url, json=body, headers=post_json_admin_header)
        assert created.status_code == HTTPStatus.CREATED
        assert_shape(created.json, TASK)
        assert created.json["spec"] == {
            "image": "example:latest", "dataset_id": repo.project.default_dataset_id, "env": {"KEY": "value"}
        }
        assert (created.json["status"], created.json["attempt"]) == ("PENDING", 1)
        contract("pull_request_task", created.json)

        again = client.post(url, json=body, headers=post_json_admin_header)
        assert again.status_code == HTTPStatus.OK
        assert again.json == created.json

        pr = client.get(f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1", headers=post_json_admin_header).json
        assert (pr["state"], pr["task_id"]) == ("YIELDED", created.json["id"])

    def test_a_bad_spec_is_rejected_and_recorded(self, client, post_json_admin_header, repo, pull_requests):
        response = client.post(
            f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1/task",
            json={"spec_raw": "not a spec"}, headers=post_json_admin_header,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert_shape(response.json, ERROR)
        pr = client.get(f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1", headers=post_json_admin_header).json
        assert (pr["state"], pr["task_id"]) == ("REJECTED", None)
        assert isinstance(pr["state_cause"], str) and pr["state_cause"]

    def test_global_batch_is_idempotent(self, client, post_json_admin_header, repo, pull_requests):
        response = client.post(
            f"/trigger_repositories/{repo.trigger_repository_id}/pull_requests/batch",
            json={"pull_requests": [pr_body(3, "2026-04-01T10:00:00Z"), pr_body(1, "2026-01-01T10:00:00Z")]},
            headers=post_json_admin_header,
        )
        assert response.status_code == HTTPStatus.CREATED
        assert_shape(response.json, {"created": [int], "existing": [int]})
        assert response.json == {"created": [3], "existing": [1]}

    def test_pull_requests_of_a_repository_are_the_provider_facts(
            self, client, simple_admin_header, repo, pull_requests, contract
        ):
        """Stored once per repository: no evaluation state, that is the project's trigger."""
        response = client.get(f"/trigger_repositories/{repo.trigger_repository_id}/pull_requests", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, REPOSITORY_PULL_REQUESTS_PAGE)
        assert set(response.json["items"][0]) == {
            "id", "trigger_repository_id", "number", "title", "raised_by", "merged_at", "merge_commit_sha",
            "base_branch", "files_truncated",
        }
        contract("repository_pull_requests_page", response.json)

    def test_per_project_triggers_are_addressed_by_assignment(
            self, client, simple_admin_header, repo, pull_requests
        ):
        url = f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1"
        response = client.get(url, headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert set(response.json) >= {"number", "state", "state_cause", "task_id"}


class TestResultsRepositories:
    def test_global_list(self, client, simple_admin_header, results_repo, results_assignment, contract):
        response = client.get("/results_repositories", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [RESULTS_REPOSITORY])
        assert [r["id"] for r in response.json] == [results_repo.id]
        contract("results_repositories", response.json)

    def test_by_id(self, client, simple_admin_header, results_repo, contract):
        response = client.get(f"/results_repositories/{results_repo.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, RESULTS_REPOSITORY)
        contract("results_repository", response.json)

    def test_project_assignments(self, client, simple_admin_header, results_repo, results_assignment, contract):
        response = client.get(f"/projects/{results_assignment.project_id}/results_repositories", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [PROJECT_RESULTS_REPOSITORY])
        [assignment] = response.json
        assert assignment["results_repository"]["uri"] == results_repo.uri
        assert (assignment["target_dir"], assignment["owned_by_federated_node"], assignment["active"]) == ("results", True, True)
        contract("project_results_repositories", response.json)

    def test_an_inactive_assignment_is_still_listed(self, client, simple_admin_header, results_assignment):
        results_assignment.revoked = True
        db.session.commit()
        response = client.get(f"/projects/{results_assignment.project_id}/results_repositories", headers=simple_admin_header)
        [assignment] = response.json
        assert (assignment["revoked"], assignment["active"]) == (True, False)

    def test_other_project_has_none(self, client, simple_admin_header, results_assignment, other_project):
        response = client.get(f"/projects/{other_project.id}/results_repositories", headers=simple_admin_header)
        assert response.json == []


class TestResults:
    def test_round_trip(self, client, post_json_admin_header, make_task, results_assignment, contract):
        task = make_task()
        body = {"task_id": task.id, "results_repository_id": results_assignment.id}

        created = client.post("/results", json=body, headers=post_json_admin_header)
        assert created.status_code == HTTPStatus.CREATED
        assert_shape(created.json, RESULT)
        assert (created.json["type"], created.json["step"], created.json["state"]) == ("PR", "UNKNOWN", "IN_PROGRESS")
        contract("result_created", created.json)

        again = client.post("/results", json=body, headers=post_json_admin_header)
        assert again.status_code == HTTPStatus.OK
        assert again.json == created.json

        patched = client.patch(
            f"/results/{created.json['id']}",
            json={"step": "OPENED", "branch": "task-1-results", "commit_sha": "a" * 40, "number": 5, "url": "https://x/pull/5"},
            headers=post_json_admin_header,
        )
        assert patched.status_code == HTTPStatus.OK
        assert_shape(patched.json, RESULT)
        contract("result_opened", patched.json)

        fetched = client.get(f"/results/{created.json['id']}", headers=post_json_admin_header)
        assert fetched.status_code == HTTPStatus.OK
        assert fetched.json == patched.json

    def test_step_filter(self, client, post_json_admin_header, make_task, results_assignment, contract):
        first, second = make_task(), make_task()
        for task, step in ((first, "PUSHED"), (second, "OPENED")):
            result = client.post(
                "/results", json={"task_id": task.id, "results_repository_id": results_assignment.id},
                headers=post_json_admin_header,
            )
            client.patch(f"/results/{result.json['id']}", json={"step": step}, headers=post_json_admin_header)

        everything = client.get("/results", headers=post_json_admin_header)
        assert_shape(everything.json, [RESULT])
        assert [r["step"] for r in everything.json] == ["PUSHED", "OPENED"]

        opened = client.get("/results?step=OPENED", headers=post_json_admin_header)
        assert_shape(opened.json, [RESULT])
        assert [r["task_id"] for r in opened.json] == [second.id]
        contract("results_by_step", opened.json)

        both = client.get("/results?step=PUSHED&step=OPENED", headers=post_json_admin_header)
        assert [r["task_id"] for r in both.json] == [first.id, second.id]
        assert client.get("/results?step=MERGED", headers=post_json_admin_header).json == []


class TestDatasets:
    def test_list(self, client, simple_admin_header, dataset, contract):
        response = client.get("/datasets", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, page_of(DATASET))
        assert (response.json["page"], response.json["total"]) == (1, 1)
        contract("datasets_page", response.json)

    def test_by_id(self, client, simple_admin_header, dataset, contract):
        response = client.get(f"/datasets/{dataset.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, DATASET)
        assert response.json["id"] == dataset.id
        contract("dataset", response.json)

    def test_by_name(self, client, simple_admin_header, dataset):
        response = client.get(f"/datasets/{dataset.name}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, DATASET)
        assert response.json["id"] == dataset.id

    def test_project_assignments(self, client, simple_admin_header, project, dataset, contract):
        response = client.get(f"/projects/{project.id}/datasets", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [PROJECT_DATASET])
        [assignment] = response.json
        assert (assignment["project_id"], assignment["enabled"], assignment["revoked"], assignment["active"]) == (
            project.id, True, False, True
        )
        assert assignment["dataset"]["id"] == dataset.id
        contract("project_datasets", response.json)

    def test_assignment_by_id(self, client, simple_admin_header, project, dataset):
        [assignment] = client.get(f"/projects/{project.id}/datasets", headers=simple_admin_header).json
        response = client.get(f"/projects/{project.id}/datasets/{assignment['id']}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, PROJECT_DATASET)
        assert response.json == assignment


class TestProjects:
    def test_list(self, client, simple_admin_header, dataset, contract):
        response = client.get("/projects", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, page_of(PROJECT))
        [item] = response.json["items"]
        assert (item["default_dataset_id"], item["locked"], item["enabled"]) == (dataset.id, False, False)
        contract("projects_page", response.json)

    def test_by_id(self, client, simple_admin_header, project, contract):
        response = client.get(f"/projects/{project.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, PROJECT)
        contract("project", response.json)


class TestHealthcheck:
    def test_body(self, client, mocker, simple_admin_header, repo, results_assignment, pull_requests, contract):
        mocker.patch(
            "app.models.git_repository.requests.get", return_value=Mock(status_code=200, ok=True, reason="OK")
        )
        response = client.get(f"/projects/{repo.project_id}/healthcheck", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, HEALTHCHECK)
        assert response.json["status"] == "ok"
        # The count is the project's own
        assert response.json["trigger_repositories"][0]["pr_count"] == 2
        contract("project_healthcheck", response.json)


class TestSecrets:
    def test_list_and_by_label(self, client, simple_admin_header, secret, contract):
        response = client.get("/secrets", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert_shape(response.json, [SECRET])
        contract("secrets_list", response.json)

        by_label = client.get(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert by_label.status_code == HTTPStatus.OK
        assert_shape(by_label.json, SECRET)
        assert by_label.json["id"] == secret.id
        contract("secret", by_label.json)


class TestTasks:
    """The task DTO, and how a task gets its dataset."""

    def post(self, client, headers, project, body):
        return client.post("/tasks", json=body, headers={**headers, "project-name": project.name})

    def test_created_through_the_api(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, dataset, contract
        ):
        created = self.post(client, post_json_admin_header, project, task_body)
        assert created.status_code == HTTPStatus.CREATED, created.json
        assert_shape(created.json, NEW_API_TASK)

        task = client.get(f"/tasks/{created.json['id']}", headers=post_json_admin_header)
        assert task.status_code == HTTPStatus.OK
        assert_shape(task.json, TASK)
        assert task.json["spec"]["dataset_id"] == dataset.id
        contract("task_api", task.json)

    def test_api_falls_back_to_the_default_dataset(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, project, dataset
        ):
        task_body["tags"].pop("dataset_id")
        created = self.post(client, post_json_admin_header, project, task_body)
        assert created.status_code == HTTPStatus.CREATED, created.json
        task = client.get(f"/tasks/{created.json['id']}", headers=post_json_admin_header)
        assert task.json["spec"]["dataset_id"] == project.default_dataset_id == dataset.id

    def test_api_rejects_another_projects_dataset(
            self, client, cr_client, registry_client, post_json_admin_header, task_body, other_project
        ):
        # The dataset in the body is the first project's, the header names the other
        response = self.post(client, post_json_admin_header, other_project, task_body)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert_shape(response.json, ERROR)
        assert "does not belong to project" in response.json["error"]

    def test_pull_request_rejects_another_projects_dataset(
            self, client, post_json_admin_header, repo, pull_requests, other_project, user_uuid
        ):
        other_secret = Secret(label="other-test-creds", provider=SecretProviderType.K8S)
        other_secret.add()
        other_dataset = Dataset(
            name="OtherDs", host="example.com", port=5432, secret_id=other_secret.id
        )
        other_dataset.add(user_id=user_uuid)
        ProjectDataset(other_project.id, other_dataset.id).add()

        response = client.post(
            f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1/task",
            json={"spec_raw": spec_file(image="example:latest", dataset=other_dataset.name)},
            headers=post_json_admin_header,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "does not belong to project" in response.json["error"]
        pr = client.get(f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1", headers=post_json_admin_header).json
        assert pr["state"] == "REJECTED"

    def test_pull_request_falls_back_to_the_default_dataset(
            self, client, post_json_admin_header, repo, pull_requests
        ):
        response = client.post(
            f"/projects/{repo.project_id}/trigger_repositories/{repo.id}/pull_requests/1/task",
            json={"spec_raw": spec_file(image="example:latest")}, headers=post_json_admin_header,
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json["spec"]["dataset_id"] == repo.project.default_dataset_id
