import json
from unittest.mock import MagicMock

import pytest
import requests
from dagster import SkipReason

from app.definitions.sensors.git.pr_process import PullRequestProcessSensor
from app.models import Project, PullRequest


def repo(id=1, project_id=1):
    return MagicMock(id=id, project_id=project_id, path="org/repo", watch_dir="specs/")


def pr(number=5):
    return PullRequest(
        trigger_repository_id=1, number=number, title="t", raised_by="dev",
        merged_at="2026-01-01T00:00:00Z", merge_commit_sha="abc", status="UNKNOWN", payload={},
    )


def spec_file(data, name="specs/a.json", status="added"):
    return [{"filename": name, "status": status}], json.dumps(data)


def make_sensor(repos=None, prs=None, files=None, contents=None, projects=None):
    backend_api = MagicMock()
    backend_api.get_projects.return_value = projects or [Project(id=1, name="p", enabled=True)]
    backend_api.get_repositories.return_value = repos if repos is not None else [repo()]
    backend_api.get_pull_requests.return_value = prs if prs is not None else [pr()]
    git_api = MagicMock()
    git_api.get_pull_request_files.return_value = files or []
    git_api.get_file_contents.return_value = contents
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    sensor = PullRequestProcessSensor(context=MagicMock(), backend_api=backend_api, git_apis=git_apis)
    return sensor, backend_api, git_api


def patched(backend_api):
    return backend_api.patch_pull_request.call_args.args[2]


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def test_a_valid_spec_creates_the_task_request_and_is_ready():
    files, contents = spec_file({"spec": {"image": "a/b:1", "env": {"K": "v"}}})
    sensor, backend_api, _ = make_sensor(files=files, contents=contents)

    result = list(sensor())

    spec = {"image": "a/b:1", "env": {"K": "v"}}
    backend_api.create_task_request.assert_called_once_with(1, 5, spec)
    assert backend_api.patch_pull_request.call_args.args[:2] == (1, 5)
    assert patched(backend_api) == {"status": "READY", "payload": spec}
    assert isinstance(result[0], SkipReason) and "Processed 1" in str(result[0])


def test_the_docker_image_key_is_accepted():
    files, contents = spec_file({"spec": {"docker_image": "a/b:1"}})
    sensor, backend_api, _ = make_sensor(files=files, contents=contents)

    list(sensor())

    assert patched(backend_api)["status"] == "READY"


def test_the_spec_is_read_at_the_merge_commit():
    files, contents = spec_file({"spec": {"image": "a/b:1"}})
    sensor, _, git_api = make_sensor(files=files, contents=contents)

    list(sensor())

    git_api.get_file_contents.assert_called_once_with(repo_path="org/repo", file_path="specs/a.json", ref="abc")


@pytest.mark.parametrize(
    "files",
    [
        [],
        [{"filename": "docs/a.json", "status": "added"}],
        [{"filename": "specs/a.txt", "status": "added"}],
        [{"filename": "specs/a.json", "status": "modified"}],
    ],
)
def test_no_watched_new_json_file_is_ignored(files):
    sensor, backend_api, _ = make_sensor(files=files)

    list(sensor())

    assert patched(backend_api) == {"status": "IGNORED", "payload": {}}
    backend_api.create_task_request.assert_not_called()


def test_several_watched_files_are_invalid():
    files = [{"filename": "specs/a.json", "status": "added"}, {"filename": "specs/b.json", "status": "added"}]
    sensor, backend_api, _ = make_sensor(files=files)

    list(sensor())

    assert patched(backend_api) == {"status": "INVALID", "payload": {}}
    backend_api.create_task_request.assert_not_called()


@pytest.mark.parametrize(
    "contents",
    ["not json", json.dumps({}), json.dumps({"spec": ["image"]}), json.dumps({"spec": {"env": {}}})],
)
def test_a_bad_spec_is_invalid(contents):
    sensor, backend_api, _ = make_sensor(files=[{"filename": "specs/a.json", "status": "added"}], contents=contents)

    list(sensor())

    assert patched(backend_api) == {"status": "INVALID", "payload": {}}
    backend_api.create_task_request.assert_not_called()


def test_a_spec_the_backend_rejects_is_invalid():
    files, contents = spec_file({"spec": {"image": "a/b:1", "bogus": 1}})
    sensor, backend_api, _ = make_sensor(files=files, contents=contents)
    backend_api.create_task_request.side_effect = http_error(400)

    list(sensor())

    assert patched(backend_api) == {"status": "INVALID", "payload": {}}


def test_a_backend_failure_leaves_the_pr_unknown_and_carries_on():
    files, contents = spec_file({"spec": {"image": "a/b:1"}})
    sensor, backend_api, _ = make_sensor(prs=[pr(5), pr(6)], files=files, contents=contents)
    backend_api.create_task_request.side_effect = [http_error(500), MagicMock()]

    list(sensor())

    assert backend_api.patch_pull_request.call_count == 1
    assert backend_api.patch_pull_request.call_args.args[:2] == (1, 6)


def test_only_repositories_of_enabled_projects_are_processed():
    projects = [Project(id=1, name="on", enabled=True), Project(id=2, name="off", enabled=False)]
    sensor, backend_api, _ = make_sensor(repos=[repo(1, 1), repo(2, 2)], projects=projects)

    list(sensor())

    backend_api.get_pull_requests.assert_called_once_with(repo_id=1, status="UNKNOWN")


def test_skips_when_no_repository_is_in_an_enabled_project():
    sensor, backend_api, _ = make_sensor(projects=[Project(id=1, name="off", enabled=False)])

    result = list(sensor())

    assert len(result) == 1 and isinstance(result[0], SkipReason)
    backend_api.get_pull_requests.assert_not_called()


def test_skips_when_there_are_no_unknown_prs():
    sensor, backend_api, _ = make_sensor(prs=[])

    result = list(sensor())

    assert "No unknown pull requests" in str(result[0])
    backend_api.patch_pull_request.assert_not_called()
