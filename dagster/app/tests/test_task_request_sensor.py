from unittest.mock import MagicMock

from dagster import RunRequest, SkipReason

from app.definitions.sensors.task_request.launcher import TaskRequestLauncherSensor
from app.models import Dataset, Project, Task, TaskRequest

DATASET = Dataset(
    id=7, project_id=1, k8s_secret_name="cdm-creds", name="cdm", host="db.host", port=5432,
    read_schema="cdm", type="postgres", slug="cdm", url="https://db.host/cdm",
)


def project(id=1, enabled=True):
    return Project(id=id, name=f"proj{id}", enabled=enabled)


def task_request(id=3, project_id=1, payload=None):
    return TaskRequest(
        id=id, pull_request_id=1, project_id=project_id, queued=True,
        payload=payload or {"image": "ghcr.io/o/i:1", "env": {"K": "v"}},
    )


def task(id=9, dataset_id=7):
    return Task(id=id, name="t", docker_image="ghcr.io/o/i:1", requested_by="u", project_id=1, dataset_id=dataset_id)


def make_backend(projects, task_requests_by_project):
    backend_api = MagicMock()
    backend_api.get_projects.return_value = projects
    backend_api.get_task_requests.side_effect = lambda queued, project_id: task_requests_by_project[project_id]
    backend_api.create_task.side_effect = lambda tr_id: task(id=tr_id + 100)
    backend_api.get_dataset.return_value = DATASET
    return backend_api


def run(backend_api):
    return list(TaskRequestLauncherSensor(context=MagicMock(), backend_api=backend_api)())


def test_skips_when_nothing_is_queued():
    backend_api = make_backend([project()], {1: []})

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], SkipReason)


def test_launches_a_queued_request():
    backend_api = make_backend([project()], {1: [task_request()]})

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], RunRequest)
    assert result[0].run_key == "task_request/3"
    assert result[0].tags == {
        "trigger": "task_request", "task_request_id": "3", "task_id": "103",
        "project_id": "1", "project": "proj1",
    }
    config = result[0].run_config["ops"]["k8s_pipes_op"]["config"]
    assert config["docker_image"] == "ghcr.io/o/i:1"
    assert config["env"] == {"K": "v"}
    assert config["dataset_name"] == "cdm"
    backend_api.create_task.assert_called_once_with(3)
    backend_api.get_dataset.assert_called_once_with(7)
    backend_api.patch_task.assert_not_called()
    backend_api.patch_task_request.assert_not_called()
    backend_api.get_task_requests.assert_called_once_with(queued=True, project_id=1)


def test_only_enabled_projects_are_acted_on():
    backend_api = make_backend(
        [project(1, enabled=False), project(2)],
        {1: [task_request(3, 1)], 2: [task_request(4, 2)]},
    )

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task_request/4"]
    backend_api.get_task_requests.assert_called_once_with(queued=True, project_id=2)


def test_a_failing_request_does_not_stop_the_others_and_stays_queued():
    backend_api = make_backend([project()], {1: [task_request(3), task_request(4)]})
    backend_api.create_task.side_effect = [RuntimeError("400 no dataset"), task(104)]

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task_request/4"]


def test_a_failing_project_does_not_stop_the_others():
    backend_api = make_backend([project(1), project(2)], {2: [task_request(4, 2)]})
    backend_api.get_task_requests.side_effect = [RuntimeError("500"), [task_request(4, 2)]]

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task_request/4"]


def test_a_request_is_not_marked_when_the_run_config_cannot_be_built():
    backend_api = make_backend([project()], {1: [task_request(payload={"env": {}})]})

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], SkipReason)
    backend_api.patch_task_request.assert_not_called()
    backend_api.patch_task.assert_not_called()


def test_the_request_stays_queued_and_the_same_run_key_is_yielded_until_a_run_starts():
    backend_api = make_backend([project()], {1: [task_request(3)]})

    first = run(backend_api)
    second = run(backend_api)

    assert [r.run_key for r in first] == [r.run_key for r in second] == ["task_request/3"]
    assert first[0].tags == second[0].tags
    backend_api.patch_task.assert_not_called()
    backend_api.patch_task_request.assert_not_called()
