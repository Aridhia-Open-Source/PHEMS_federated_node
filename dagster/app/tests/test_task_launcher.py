from unittest.mock import MagicMock

from dagster import RunRequest, SkipReason

from app.definitions.sensors.task.launcher import TaskLauncherSensor
from app.models import Dataset, Project, ProjectDataset, Task

DATASET = Dataset(
    id=7, secret={"id": 3, "project_id": 1, "label": "cdm-creds", "provider": "K8S", "key": "cdm-creds-abc", "enabled": True}, name="cdm", host="db.host", port=5432,
    read_schema="cdm", type="postgres", enabled=True, slug="cdm", url="https://db.host/cdm",
)


def assignment(active=True, dataset=DATASET):
    return ProjectDataset(
        id=3, project_id=1, dataset=dataset, enabled=active, revoked=False, active=active
    )


def project(id=1, enabled=True):
    return Project(id=id, name=f"proj{id}", enabled=enabled)


def task(id=9, project_id=1, attempt=1, dataset_id=7):
    return Task(
        id=id, name="t", spec={"image": "ghcr.io/o/i:1", "dataset_id": dataset_id, "env": {"K": "v"}},
        attempt=attempt, requested_by="u", project_id=project_id, trigger_id=4, status="PENDING",
    )


def make_backend(projects, tasks_by_project):
    backend_api = MagicMock()
    # The backend filters the projects
    backend_api.get_projects.side_effect = lambda enabled: [p for p in projects if p.enabled == enabled]
    backend_api.get_tasks.side_effect = lambda status, project_id: tasks_by_project[project_id]
    backend_api.get_project_dataset.return_value = assignment()
    backend_api.get_task_config.return_value = {"current": True, "changes": [], "config_hash": None, "revoked": []}
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
    assert config["dataset"]["name"] == "cdm"
    backend_api.get_project_dataset.assert_called_once_with(1, 7)
    backend_api.get_tasks.assert_called_once_with(status="PENDING", project_id=1)


def test_a_task_without_a_dataset_is_launched_without_fetching_one():
    backend_api = make_backend([project()], {1: [task(dataset_id=None)]})

    result = run(backend_api)

    assert isinstance(result[0], RunRequest)
    config = result[0].run_config["ops"]["k8s_pipes_op"]["config"]
    assert config["docker_image"] == "ghcr.io/o/i:1"
    assert "dataset" not in config
    backend_api.get_project_dataset.assert_not_called()


def test_a_task_whose_dataset_is_not_active_is_not_launched():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_project_dataset.return_value = assignment(active=False)

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], SkipReason)
    backend_api.patch_task.assert_called_once_with(
        1, 9, {"status": "FAILED", "state_cause": "Dataset cdm is not active in project proj1"}
    )


def test_a_task_whose_dataset_secret_is_disabled_is_failed_with_the_cause():
    backend_api = make_backend([project()], {1: [task()]})
    secret = DATASET.secret.model_copy(update={"enabled": False})
    backend_api.get_project_dataset.return_value = assignment(dataset=DATASET.model_copy(update={"secret": secret}))

    result = run(backend_api)

    assert len(result) == 1 and isinstance(result[0], SkipReason)
    backend_api.patch_task.assert_called_once_with(
        1, 9, {"status": "FAILED", "state_cause": "The secret of dataset cdm is disabled"}
    )


def test_other_tasks_are_launched_when_one_dataset_is_not_active():
    backend_api = make_backend([project()], {1: [task(id=9, dataset_id=7), task(id=10, dataset_id=None)]})
    backend_api.get_project_dataset.return_value = assignment(active=False)

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/10/1"]
    backend_api.patch_task.assert_called_once()


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
    backend_api.get_projects.assert_called_once_with(enabled=True)
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


def test_a_task_is_checked_against_its_configuration_before_launch():
    backend_api = make_backend([project()], {1: [task()]})

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/9/1"]
    backend_api.get_task_config.assert_called_once_with(1, 9)
    backend_api.patch_task.assert_not_called()


def test_a_task_whose_configuration_changed_is_failed_and_the_next_is_launched():
    backend_api = make_backend([project()], {1: [task(id=9), task(id=10)]})
    backend_api.get_task_config.side_effect = lambda project_id, task_id: (
        {"current": False, "changes": ["image changed", "env changed"], "config_hash": "h", "revoked": []}
        if task_id == 9 else {"current": True, "changes": [], "config_hash": None, "revoked": []}
    )

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/10/1"]
    backend_api.patch_task.assert_called_once_with(1, 9, {
        "status": "FAILED",
        "state_cause": "task configuration changed since the task was created: image changed; env changed",
    })


def test_a_task_with_a_revoked_resource_is_failed_and_not_launched():
    backend_api = make_backend([project()], {1: [task(id=9), task(id=10)]})
    backend_api.get_task_config.side_effect = lambda project_id, task_id: {
        "current": True, "changes": [], "config_hash": None,
        "revoked": ["dataset ds", "results repository org/results"] if task_id == 9 else [],
    }

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/10/1"]
    backend_api.patch_task.assert_called_once_with(1, 9, {
        "status": "FAILED", "state_cause": "revoked: dataset ds; results repository org/results",
    })
    # the dataset link is not read for it: the task failed before
    backend_api.get_project_dataset.assert_called_once()


def test_revoked_is_the_cause_of_a_task_that_is_also_stale():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.return_value = {
        "current": False, "changes": ["image changed"], "config_hash": "h", "revoked": ["trigger repository org/repo"],
    }

    assert [r for r in run(backend_api) if isinstance(r, RunRequest)] == []
    backend_api.patch_task.assert_called_once_with(1, 9, {
        "status": "FAILED", "state_cause": "revoked: trigger repository org/repo",
    })


def test_the_revoked_cause_is_cut_to_the_column_length():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.return_value = {
        "current": True, "changes": [], "config_hash": None, "revoked": ["dataset " + "x" * 2000],
    }

    run(backend_api)

    assert len(backend_api.patch_task.call_args.args[2]["state_cause"]) == 1024


def test_the_stale_cause_is_cut_to_the_column_length():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.return_value = {"current": False, "changes": ["x" * 2000], "config_hash": None, "revoked": []}

    run(backend_api)

    assert len(backend_api.patch_task.call_args.args[2]["state_cause"]) == 1024


def test_an_error_for_one_task_leaves_it_pending_and_does_not_stop_the_others():
    backend_api = make_backend([project()], {1: [task(id=9), task(id=10)]})
    backend_api.get_task_config.side_effect = lambda project_id, task_id: (
        (_ for _ in ()).throw(RuntimeError("backend down"))
        if task_id == 9 else {"current": True, "changes": [], "config_hash": None, "revoked": []}
    )

    result = run(backend_api)

    assert [r.run_key for r in result] == ["task/10/1"]
    backend_api.patch_task.assert_not_called()


def test_a_task_with_an_error_is_launched_by_a_later_tick_with_the_same_run_key():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.side_effect = [
        RuntimeError("backend down"), {"current": True, "changes": [], "config_hash": None, "revoked": []}
    ]

    first = run(backend_api)
    second = run(backend_api)

    assert len(first) == 1 and isinstance(first[0], SkipReason)
    assert [r.run_key for r in second] == ["task/9/1"]
    backend_api.patch_task.assert_not_called()


def config_with(**fields):
    return {"current": True, "changes": [], "config_hash": None, "revoked": [], **fields}


def test_a_revoked_and_disabled_project_keeps_its_task_pending_until_it_is_enabled_then_fails_it():
    pending = task()
    revoked_config = config_with(revoked=["project proj1", "results repository org/results"])
    backend_api = make_backend([project(enabled=False)], {1: [pending]})
    backend_api.get_task_config.return_value = revoked_config

    # Disabled: the launcher reads enabled projects only, so it neither reads the task nor patches it
    first = run(backend_api)

    assert len(first) == 1 and isinstance(first[0], SkipReason)
    backend_api.get_projects.assert_called_once_with(enabled=True)
    backend_api.get_tasks.assert_not_called()
    backend_api.get_task_config.assert_not_called()
    backend_api.patch_task.assert_not_called()

    # Enabled while still revoked: the task fails with the revoked cause and is not launched
    backend_api = make_backend([project(enabled=True)], {1: [pending]})
    backend_api.get_task_config.return_value = revoked_config

    second = run(backend_api)

    assert len(second) == 1 and isinstance(second[0], SkipReason)
    backend_api.patch_task.assert_called_once_with(1, 9, {
        "status": "FAILED", "state_cause": "revoked: project proj1; results repository org/results",
    })


def test_a_task_with_a_revoked_dataset_is_failed_naming_the_dataset_with_the_revoked_prefix():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.return_value = config_with(revoked=["dataset cdm"])

    result = run(backend_api)

    assert [r for r in result if isinstance(r, RunRequest)] == []
    backend_api.patch_task.assert_called_once_with(1, 9, {"status": "FAILED", "state_cause": "revoked: dataset cdm"})
    backend_api.get_project_dataset.assert_not_called()


def test_a_task_whose_global_dataset_is_switched_off_is_failed_naming_the_dataset():
    backend_api = make_backend([project()], {1: [task()]})
    # The link is not active when the global dataset is disabled
    backend_api.get_project_dataset.return_value = assignment(
        active=False, dataset=DATASET.model_copy(update={"enabled": False})
    )

    run(backend_api)

    cause = backend_api.patch_task.call_args.args[2]["state_cause"]
    assert cause == "Dataset cdm is not active in project proj1"
    assert not cause.startswith("revoked:")


def test_a_stale_task_is_failed_as_stale_before_its_dataset_link_is_read():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.return_value = config_with(current=False, changes=["image changed"])
    backend_api.get_project_dataset.return_value = assignment(active=False)

    run(backend_api)

    backend_api.patch_task.assert_called_once_with(1, 9, {
        "status": "FAILED", "state_cause": "task configuration changed since the task was created: image changed",
    })
    backend_api.get_project_dataset.assert_not_called()


def test_an_inactive_dataset_link_is_the_cause_before_a_disabled_dataset_secret():
    backend_api = make_backend([project()], {1: [task()]})
    secret = DATASET.secret.model_copy(update={"enabled": False})
    backend_api.get_project_dataset.return_value = assignment(
        active=False, dataset=DATASET.model_copy(update={"secret": secret})
    )

    run(backend_api)

    backend_api.patch_task.assert_called_once_with(
        1, 9, {"status": "FAILED", "state_cause": "Dataset cdm is not active in project proj1"}
    )


def test_a_task_failed_by_a_rule_is_patched_once_and_never_launched():
    backend_api = make_backend([project()], {1: [task()]})
    backend_api.get_task_config.return_value = config_with(
        revoked=["dataset cdm"], current=False, changes=["image changed"]
    )
    backend_api.get_project_dataset.return_value = assignment(active=False)

    result = run(backend_api)

    assert not any(isinstance(r, RunRequest) for r in result)
    backend_api.patch_task.assert_called_once()
    backend_api.get_project_dataset.assert_not_called()
