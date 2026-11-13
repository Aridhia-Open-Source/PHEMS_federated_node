"""
What `apply` and `delete` do with a file that names what it does not hold (a project's dataset and repositories): the
Applier and the delete rows, with the backend faked.
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

from fncli.nodefile.apply import Applier, to_do
from fncli.nodefile.delete import DELETE, Remover, deletions
from fncli.nodefile.diff import BLOCKED, CREATE, UNCHANGED, BackendState, diff
from fncli.tests.test_nodefile_diff import make_node, node_data, synced_state, without_globals


def fake_api() -> MagicMock:
    """Finds the entities the synced state holds, with ids, and makes a project with id 1"""
    api = MagicMock()
    api.get_or_create_project.return_value = SimpleNamespace(id=1)
    api.find_dataset.return_value = SimpleNamespace(id=20, name="shared")
    api.find_trigger_repository.return_value = SimpleNamespace(id=10)
    api.find_results_repository.return_value = SimpleNamespace(id=11)
    return api


def test_a_new_project_is_assigned_the_dataset_and_repositories_found_on_the_node():
    state = replace(synced_state(), projects=[])
    node = make_node(without_globals())
    api = fake_api()
    todo = to_do(diff(node, state))

    assert [(change.action, change.kind, change.name) for change in todo] == [(CREATE, "project", "alpha")]
    for change in todo:
        Applier(node, state, api, None).run(change)

    api.get_or_create_project.assert_called_once_with("alpha")
    api.find_dataset.assert_called_with("shared")
    api.get_or_assign_dataset.assert_called_once_with(1, api.find_dataset.return_value)
    api.put_project_trigger_repository.assert_called_once_with(1, 10, "specs/", "main", True)
    api.put_project_results_repository.assert_called_once_with(1, 11, "results/", "main", True)
    api.patch_project.assert_called_once_with(1, {"enabled": True})


def test_a_project_with_a_reference_that_is_nowhere_is_not_applied_at_all():
    state = replace(synced_state(), datasets=[], projects=[])
    changes = diff(make_node(without_globals()), state)

    assert [change.action for change in changes if change.kind == "project"] == [BLOCKED]
    assert to_do(changes) == []


def test_a_blocked_repository_is_left_out_of_what_apply_does_and_the_rest_is_still_done():
    data = node_data()
    data["repositories"]["results"][0]["secret"] = "nope-creds"
    del data["gitea"]
    changes = diff(make_node(data), BackendState([], set(), [], [], [], []))

    todo = [(change.kind, change.name) for change in to_do(changes)]

    assert ("results repo", "gitea_admin/results-repo") not in todo
    assert ("project", "alpha") not in todo
    assert ("trigger repo", "gitea_admin/trigger-repo") in todo


def test_deleting_a_projects_file_with_all_leaves_the_dataset_and_repositories_it_only_names():
    node = make_node(without_globals())
    rows, absent = deletions(node, synced_state(), with_globals=True)

    # The provider is kept: the repositories outside the file are on it
    assert [(row.action, row.kind, row.name) for row in rows] == [
        (DELETE, "project", "alpha"), (UNCHANGED, "provider", "gitea-local"),
    ]
    assert absent == 0

    api = MagicMock()
    api.find_project.return_value = SimpleNamespace(id=1)
    for row in rows:
        if row.action == DELETE:
            Remover(api).run(row)
    api.delete_project.assert_called_once_with(1)
    api.delete_dataset.assert_not_called()
    api.delete_repository.assert_not_called()


def test_deleting_the_datasets_own_file_lists_the_project_outside_it_that_uses_the_dataset():
    data = node_data()
    data["repositories"] = {"triggers": [], "results": []}
    data["secrets"] = {"dataset-creds": data["secrets"]["dataset-creds"]}
    data["projects"] = []
    del data["gitea"]
    del data["providers"]

    rows, _ = deletions(make_node(data), synced_state(), with_globals=True)

    assert [(row.action, row.kind, row.name, row.also_used_by) for row in rows] == [
        (DELETE, "dataset", "Shared", ("alpha",)),
        (DELETE, "secret", "dataset-creds", ()),
    ]
    assert UNCHANGED not in {row.action for row in rows}
