from unittest.mock import MagicMock

from dagster import RunRequest, SkipReason

from app.definitions.sensors.task.launcher import TaskLauncherSensor
from app.models import Dataset, Project, Task

DATASET = Dataset(
    id=7, project_id=1, k8s_secret_name="cdm-creds", name="cdm", host="db.host", port=5432,
    read_schema="cdm", type="postgres", slug="cdm", url="https://db.host/cdm",
)


def project(id=1, enabled=True):
    return Project(id=id, name=f"proj{id}", enabled=enabled)


def task(id=9, project_id=1, attempt=1, dataset_id=7):
    return Task(
        id=id, name="t", docker_image="ghcr.io/o/i:1", spec={"image": "ghcr.io/o/i:1", "env": {"K": "v"}},
        attempt=attempt, requested_by="u", project_id=project_id, trigger_id=4, dataset_id=dataset_id,
        status="PENDING",
    )


def make_backend(projects, tasks_by_project):
    backend_api = MagicMock()
    backend_api.get_projects.return_value = projects
    backend_api.get_tasks.side_effect = lambda status, project_id: tasks_by_project[project_id]
    backend_api.get_dataset.return_value = DATASET
    return backend_api


def run(backend_api):
    return list(TaskLauncherSensor(context=MagicMock(), backend_api=backend_api)())


def test_skips_when_nothing_is_pending():
    result = run(make_backend([project()], {1: []}))

    assert len(result) == 1 and isinstance(result[0], SkipReason)


def test_launches_a_pending_task():
    backend_api = make_backend([project()], {1: [task()]})

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], RunRequest)
    assert result[0].run_key == "task/9/1"
    assert result[0].tags == {
        "trigger": "task", "task_id": "9", "attempt": "1", "project_id": "1", "project": "proj1",
    }
    config = result[0].run_config["ops"]["k8s_pipes_op"]["config"]
    assert config["docker_image"] == "ghcr.io/o/i:1"
    assert config["env"] == {"K": "v"}
    assert config["dataset_name"] == "cdm"
    backend_api.get_dataset.assert_called_once_with(7)
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_id=1)


def test_the_run_key_includes_the_attempt():
    result = run(make_backend([project()], {1: [task(attempt=2)]}))

    assert result[0].run_key == "task/9/2"
    assert result[0].tags["attempt"] == "2"


def test_only_enabled_projects_are_acted_on():
    backend_api = make_backend(
        [project(1, enabled=False), project(2)], {1: [task(3, 1)], 2: [task(4, 2)]},
    )

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/4/1"]
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_id=2)


def test_every_pending_task_of_every_page_is_launched():
    """get_tasks follows the pages, so the launcher sees them all."""
    backend_api = make_backend([project()], {1: [task(i) for i in range(1, 251)]})

    assert len(run(backend_api)) == 250


def test_the_launcher_patches_nothing_and_re_yields_the_same_run_key():
    backend_api = make_backend([project()], {1: [task()]})

    first = run(backend_api)
    second = run(backend_api)

    assert [r.run_key for r in first] == [r.run_key for r in second] == ["task/9/1"]
    backend_api.patch_task.assert_not_called()
