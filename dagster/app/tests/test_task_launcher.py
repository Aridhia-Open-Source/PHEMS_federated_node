import json
from pathlib import Path
from unittest.mock import MagicMock

from dagster import RunRequest, SkipReason

from app.definitions.run_config import build_run_config
from app.definitions.sensors.task.launcher import TaskLauncherSensor
from app.models import Dataset, LaunchDecision, Project, Task

DATASET = Dataset(
    id=7, secret={"id": 3, "project_id": 1, "label": "cdm-creds", "provider": "K8S", "key": "cdm-creds-abc", "enabled": True}, name="cdm", host="db.host", port=5432,
    read_schema="cdm", type="postgres", enabled=True, slug="cdm", url="https://db.host/cdm",
)


def decision(task_, outcome="launch", cause=None, dataset=DATASET):
    """The backend's answer to the launch call: the decision and, for a task with a dataset, the dataset."""
    return LaunchDecision(
        outcome=outcome, cause=cause, task=task_, dataset=dataset if task_.spec.dataset_id and outcome == "launch" else None
    )


def failing(task_, cause):
    """The backend's answer for a task it decided to fail (and has already moved to FAILED)."""
    return decision(task_, "fail", cause)




def project(id=1, enabled=True):
    return Project(id=id, name=f"proj{id}", enabled=enabled)


def task(id=9, project_id=1, attempt=1, dataset_id=7):
    return Task(
        id=id, name="t", spec={"image": "ghcr.io/o/i:1", "dataset_id": dataset_id, "env": {"K": "v"}},
        attempt=attempt, requested_by="u", project_id=project_id, trigger_id=4, status="PENDING",
    )


def make_backend(projects, tasks_by_project):
    backend_api = MagicMock()
    # The backend filters the tasks by their project's enabled flag, and lists them by id
    enabled = {p.id for p in projects if p.enabled}
    backend_api.get_tasks.side_effect = lambda status, project_enabled: sorted(
        (t for ts in tasks_by_project.values() for t in ts if t.project_id in enabled), key=lambda t: t.id
    )
    tasks = {t.id: t for ts in tasks_by_project.values() for t in ts}
    backend_api.launch_task.side_effect = lambda project_id, task_id: decision(tasks[task_id])
    return backend_api


def run(backend_api):
    return list(TaskLauncherSensor(context=MagicMock(), backend_api=backend_api)())


def test_skips_when_nothing_is_pending():
    result = run(make_backend([project()], {1: []}))

    assert len(result) == 1 and isinstance(result[0], SkipReason)


def test_launches_a_pending_task_with_one_call():
    backend_api = make_backend([project()], {1: [task()]})

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], RunRequest)
    assert result[0].run_key == "task/9/1"
    assert result[0].tags == {
        "trigger": "task", "task_id": "9", "attempt": "1", "project_id": "1",
    }
    config = result[0].run_config["ops"]["k8s_pipes_op"]["config"]
    assert config["docker_image"] == "ghcr.io/o/i:1"
    assert config["env"] == {"K": "v"}
    assert config["dataset"]["name"] == "cdm"
    backend_api.launch_task.assert_called_once_with(1, 9)
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_enabled=True)
    backend_api.get_task_config.assert_not_called()
    backend_api.get_project_dataset.assert_not_called()
    backend_api.patch_task.assert_not_called()


def test_the_run_is_built_from_what_the_launch_response_carries():
    listed = task(dataset_id=7)
    answered = task(dataset_id=7)
    answered.spec.env = {"K": "from-the-response"}
    backend_api = make_backend([project()], {1: [listed]})
    backend_api.launch_task.side_effect = None
    backend_api.launch_task.return_value = decision(answered)

    result = run(backend_api)

    assert result[0].run_config["ops"]["k8s_pipes_op"]["config"]["env"] == {"K": "from-the-response"}


def test_a_task_without_a_dataset_is_launched_without_one():
    backend_api = make_backend([project()], {1: [task(dataset_id=None)]})

    result = run(backend_api)

    assert isinstance(result[0], RunRequest)
    config = result[0].run_config["ops"]["k8s_pipes_op"]["config"]
    assert config["docker_image"] == "ghcr.io/o/i:1"
    assert "dataset" not in config


def test_a_task_the_backend_fails_is_not_launched_and_nothing_more_is_called():
    failed = task()
    backend_api = make_backend([project()], {1: [failed]})
    backend_api.launch_task.side_effect = None
    backend_api.launch_task.return_value = failing(failed, "Dataset cdm is not active in project proj1")

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], SkipReason)
    # the backend moved the task to FAILED itself
    backend_api.launch_task.assert_called_once_with(1, 9)
    backend_api.patch_task.assert_not_called()
    backend_api.get_project_dataset.assert_not_called()


def test_a_task_no_longer_pending_is_skipped():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.launch_task.side_effect = None
    backend_api.launch_task.return_value = None

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], SkipReason)
    backend_api.patch_task.assert_not_called()


def test_other_tasks_are_launched_when_one_is_failed():
    failed, other = task(id=9, dataset_id=7), task(id=10, dataset_id=None)
    backend_api = make_backend([project()], {1: [failed, other]})
    backend_api.launch_task.side_effect = lambda project_id, task_id: (
        failing(failed, "The secret of dataset cdm is disabled") if task_id == 9 else decision(other)
    )

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/10/1"]
    backend_api.patch_task.assert_not_called()


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
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_enabled=True)
    backend_api.launch_task.assert_called_once_with(2, 4)


def test_tasks_of_two_projects_are_launched_each_with_its_own_project_id():
    backend_api = make_backend([project(1), project(2)], {1: [task(3, 1)], 2: [task(4, 2)]})

    result = run(backend_api)

    assert [(r.run_key, r.tags["project_id"]) for r in result] == [("task/3/1", "1"), ("task/4/1", "2")]
    assert [c.args for c in backend_api.launch_task.call_args_list] == [(1, 3), (2, 4)]
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_enabled=True)


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


def test_an_error_for_one_task_leaves_it_pending_and_does_not_stop_the_others():
    first, second = task(id=9), task(id=10)
    backend_api = make_backend([project()], {1: [first, second]})
    backend_api.launch_task.side_effect = lambda project_id, task_id: (
        (_ for _ in ()).throw(RuntimeError("backend down")) if task_id == 9 else decision(second)
    )

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/10/1"]
    backend_api.patch_task.assert_not_called()


def test_a_task_with_an_error_is_launched_by_a_later_tick_with_the_same_run_key():
    pending = task()
    backend_api = make_backend([project()], {1: [pending]})
    backend_api.launch_task.side_effect = [RuntimeError("backend down"), decision(pending)]

    first = run(backend_api)
    second = run(backend_api)

    assert len(first) == 1 and isinstance(first[0], SkipReason)
    assert [r.run_key for r in second] == ["task/9/1"]
    backend_api.patch_task.assert_not_called()


def test_a_disabled_project_keeps_its_task_pending_until_it_is_enabled_then_the_backend_fails_it():
    pending = task()
    backend_api = make_backend([project(enabled=False)], {1: [pending]})

    # Disabled: the launcher reads enabled projects only, so it neither reads the task nor launches it
    first = run(backend_api)

    assert len(first) == 1 and isinstance(first[0], SkipReason)
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_enabled=True)
    backend_api.launch_task.assert_not_called()

    # Enabled while revoked: the backend fails the task; the launcher yields no run
    backend_api = make_backend([project(enabled=True)], {1: [pending]})
    backend_api.launch_task.side_effect = None
    backend_api.launch_task.return_value = failing(pending, "revoked: project proj1")

    second = run(backend_api)

    assert len(second) == 1 and isinstance(second[0], SkipReason)
    backend_api.launch_task.assert_called_once_with(1, 9)
    backend_api.patch_task.assert_not_called()


def test_a_sample_launch_response_of_the_backend_parses_and_builds_a_run_config():
    """The sample is checked against the real response by nexus-api's tests/test_task_launch.py."""
    sample = json.loads((Path(__file__).parent / "contract" / "launch_response.json").read_text())

    parsed = LaunchDecision.model_validate(sample)

    assert (parsed.outcome, parsed.task.id, parsed.dataset.name) == ("launch", 1, "globalds")
    config = build_run_config(parsed.task.spec, parsed.dataset)["ops"]["k8s_pipes_op"]["config"]
    assert config["docker_image"] == "img:1"
    assert config["dataset"]["secret"]["key"] == "fn-secret-test-creds"


def test_a_sample_task_list_response_of_the_backend_parses_into_tasks():
    """The sample is checked against the real response by nexus-api's tests/test_all_tasks_list.py."""
    sample = json.loads((Path(__file__).parent / "contract" / "tasks_response.json").read_text())

    tasks = [Task(**t) for t in sample["tasks"]]

    assert [(t.id, t.project_id, t.status) for t in tasks] == [(1, 1, "PENDING")]
