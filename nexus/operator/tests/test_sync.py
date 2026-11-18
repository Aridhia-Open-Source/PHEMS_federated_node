from types import SimpleNamespace
from unittest.mock import MagicMock, call

import kopf
import pytest

from nexus_operator import sync


def record(**fields):
    """A client model as the sync reads it: attributes plus model_dump()"""
    return SimpleNamespace(**fields, model_dump=lambda: fields)


@pytest.fixture
def api():
    api = MagicMock()
    api.get_secrets.return_value = [{"label": "creds", "owner_group": "service"}]
    api.get_git_providers.return_value = [
        record(
            id=1, name="github", type="github", uri="https://github.com", api_uri="https://api.github.com",
            owner_group="service",
        ),
    ]
    return api


def test_provider_created_when_missing(api):
    api.get_git_providers.return_value = []
    api.get_or_create_git_provider.return_value = record(id=7)

    result = sync.sync_provider(api, "gitea", {"type": "gitea", "uri": "http://gitea:4000/", "apiUri": "http://gitea:4000/api/v1"})

    api.get_or_create_git_provider.assert_called_once_with("http://gitea:4000", "gitea", "gitea", "http://gitea:4000/api/v1")
    assert (result.nexus_id, result.changed) == (7, True)


def test_provider_patched_with_only_what_differs(api):
    result = sync.sync_provider(api, "github", {"type": "github", "uri": "https://github.com/", "apiUri": "https://api.github.com/"})
    assert not result.changed
    api.patch_git_provider.assert_not_called()

    sync.sync_provider(api, "gh", {"type": "github", "uri": "https://github.com"})
    api.patch_git_provider.assert_called_once_with(1, {"name": "gh"})


def test_provider_made_by_hand_that_matches_is_left_alone(api):
    api.get_git_providers.return_value = [
        record(id=1, name="github", type="github", uri="https://github.com", api_uri="https://api.github.com",
               owner_group=None),
    ]
    result = sync.sync_provider(api, "github", {"type": "github", "uri": "https://github.com"})
    api.patch_git_provider.assert_not_called()
    assert not result.changed


def test_secret_sent_only_when_a_source_changed(api):
    sources = {"db": ({"username": "u", "password": "p"}, "5")}
    spec = {"values": {
        "USERNAME": {"secretKeyRef": {"name": "db", "key": "username"}},
        "PASSWORD": {"secretKeyRef": {"name": "db", "key": "password"}},
    }}

    def read(namespace, name):
        return sources[name]

    result = sync.sync_secret(api, "creds", spec, "fn", read, {"db": "5"}, False)
    assert not result.changed
    api.upsert_secret.assert_not_called()

    result = sync.sync_secret(api, "creds", spec, "fn", read, {"db": "4"}, False)
    api.upsert_secret.assert_called_once_with("creds", {"USERNAME": "u", "PASSWORD": "p"})
    assert result.status == {"sourceVersions": {"db": "5"}}


def test_secret_sent_when_the_spec_changed_with_the_same_source(api):
    spec = {"values": {"TOKEN": {"secretKeyRef": {"name": "db", "key": "b"}}}}
    result = sync.sync_secret(api, "creds", spec, "fn", lambda ns, n: ({"a": "1", "b": "2"}, "5"), {"db": "5"}, True)
    api.upsert_secret.assert_called_once_with("creds", {"TOKEN": "2"})
    assert result.changed


def test_secret_made_by_hand_not_sent_while_its_source_is_unchanged(api):
    api.get_secrets.return_value = [{"label": "creds", "owner_group": None}]
    sync.sync_secret(api, "creds", {"fromSecret": {"name": "app"}}, "fn", lambda ns, n: ({"APP_ID": "1"}, "3"), {"app": "3"}, False)
    api.upsert_secret.assert_not_called()


def test_secret_sent_when_the_record_is_missing(api):
    api.get_secrets.return_value = []
    sync.sync_secret(api, "creds", {"fromSecret": {"name": "app"}}, "fn", lambda ns, n: ({"APP_ID": "1"}, "3"), {"app": "3"}, False)
    api.upsert_secret.assert_called_once_with("creds", {"APP_ID": "1"})


def test_repository_waits_for_its_provider_and_secret(api):
    api.get_secrets.return_value = []
    with pytest.raises(kopf.TemporaryError, match="a git provider on gitea:4000, secret creds"):
        sync.sync_repository(api, "r", {"type": "trigger", "uri": "http://gitea:4000/org/repo", "secret": "creds"})
    api.create_repository.assert_not_called()


def test_repository_adopted_and_patched(api):
    api.find_results_repository.return_value = record(id=3, provider=record(id=1), secret=record(label="old"), owner_group="service")
    result = sync.sync_repository(api, "r", {"type": "results", "uri": "https://github.com/org/out", "secret": "creds"})
    api.patch_results_repository.assert_called_once_with(3, {"secret_label": "creds"})
    assert (result.nexus_id, result.changed) == (3, True)


def test_dataset_created(api):
    api.find_dataset.return_value = None
    api.create_dataset.return_value = record(id=4)
    sync.sync_dataset(api, "omop", {"type": "postgres", "host": "db", "port": 5432, "secret": "creds"})
    api.create_dataset.assert_called_once_with("omop", "db", 5432, "postgres", "creds", read_schema=None, write_schema=None)


PROJECT = {
    "datasets": ["omop"],
    "repositories": {
        "triggers": [{"repository": "https://github.com/org/in", "watchDir": "specs/", "baseBranch": "main"}],
        "results": {"repository": "https://github.com/org/out", "targetDir": "results", "baseBranch": "main"},
    },
}


def test_project_waits_for_what_it_names(api):
    api.find_dataset.return_value = None
    api.find_trigger_repository.return_value = record(id=2)
    api.find_results_repository.return_value = None
    with pytest.raises(kopf.TemporaryError, match="dataset omop, results repository https://github.com/org/out"):
        sync.sync_project(api, "cohort", PROJECT)
    api.get_or_create_project.assert_not_called()


def test_new_project_created_disabled_then_enabled_last(api):
    dataset, trigger, results = record(id=4), record(id=2), record(id=3)
    api.find_dataset.return_value = dataset
    api.find_trigger_repository.return_value = trigger
    api.find_results_repository.return_value = results
    api.find_project.return_value = None
    api.get_or_create_project.return_value = record(id=9, enabled=False, owner_group="service")
    api.get_project_datasets.return_value = []
    api.get_project_trigger_repositories.return_value = []
    api.get_project_results_repositories.return_value = []

    result = sync.sync_project(api, "cohort", PROJECT)

    api.get_or_assign_dataset.assert_called_once_with(9, dataset)
    api.put_project_trigger_repository.assert_called_once_with(9, 2, watch_dir="specs/", base_branch="main", enabled=True)
    api.put_project_results_repository.assert_called_once_with(9, 3, target_dir="results", base_branch="main", enabled=True)
    assert api.patch_project.call_args_list == [call(9, {"enabled": True})]
    assert (result.nexus_id, result.changed) == (9, True)


def test_live_project_only_patched_where_it_differs(api):
    api.find_dataset.return_value = record(id=4)
    api.find_trigger_repository.return_value = record(id=2)
    api.find_results_repository.return_value = record(id=3)
    api.find_project.return_value = record(id=9, enabled=True, owner_group="service")
    api.get_project_datasets.return_value = [record(dataset=record(id=4))]
    api.get_project_trigger_repositories.return_value = [
        record(trigger_repository=record(id=2), watch_dir="specs", base_branch="dev", enabled=True),
    ]
    api.get_project_results_repositories.return_value = [
        record(results_repository=record(id=3), target_dir="results/", base_branch="main", enabled=True),
    ]

    result = sync.sync_project(api, "cohort", PROJECT)

    api.patch_project_trigger_repository.assert_called_once_with(9, 2, {"base_branch": "main"})
    api.put_project_results_repository.assert_not_called()
    api.patch_project_results_repository.assert_not_called()
    api.patch_project.assert_not_called()
    assert result.changed


def test_live_project_disabled_to_change_its_results_repository(api):
    api.find_dataset.return_value = record(id=4)
    api.find_trigger_repository.return_value = record(id=2)
    api.find_results_repository.return_value = record(id=5)
    api.find_project.return_value = record(id=9, enabled=True, owner_group="service")
    api.get_project_datasets.return_value = [record(dataset=record(id=4))]
    api.get_project_trigger_repositories.return_value = [
        record(trigger_repository=record(id=2), watch_dir="specs", base_branch="main", enabled=True),
    ]
    api.get_project_results_repositories.return_value = [
        record(results_repository=record(id=3), target_dir="results", base_branch="main", enabled=True),
    ]

    sync.sync_project(api, "cohort", PROJECT)

    order = [c for c in api.mock_calls if c[0] in (
        "patch_project", "delete_project_results_repository", "put_project_results_repository",
    )]
    assert order == [
        call.patch_project(9, {"enabled": False}),
        call.delete_project_results_repository(9, 3),
        call.put_project_results_repository(9, 5, target_dir="results", base_branch="main", enabled=True),
        call.patch_project(9, {"enabled": True}),
    ]


def test_project_enabled_with_backfill_only_when_it_was_disabled(api):
    api.find_dataset.return_value = record(id=4)
    api.find_trigger_repository.return_value = record(id=2)
    api.find_results_repository.return_value = record(id=5)
    api.find_project.return_value = record(id=9, enabled=False, owner_group="service")
    api.get_project_datasets.return_value = [record(dataset=record(id=4))]
    api.get_project_trigger_repositories.return_value = [
        record(trigger_repository=record(id=2), watch_dir="specs", base_branch="main", enabled=True),
    ]
    api.get_project_results_repositories.return_value = [
        record(results_repository=record(id=5), target_dir="results", base_branch="main", enabled=True),
    ]

    sync.sync_project(api, "cohort", {**PROJECT, "backfill": True})
    api.patch_project.assert_called_once_with(9, {"enabled": True, "backfill": True})

    # Live, and disabled only to swap its results repository: the re-enable never backfills
    api.patch_project.reset_mock()
    api.find_project.return_value = record(id=9, enabled=True, owner_group="service")
    api.get_project_results_repositories.return_value = [
        record(results_repository=record(id=3), target_dir="results", base_branch="main", enabled=True),
    ]
    sync.sync_project(api, "cohort", {**PROJECT, "backfill": True})
    assert api.patch_project.call_args_list == [call(9, {"enabled": False}), call(9, {"enabled": True})]


def test_project_made_by_hand_that_matches_is_left_alone(api):
    api.find_dataset.return_value = record(id=4)
    api.find_trigger_repository.return_value = record(id=2)
    api.find_results_repository.return_value = record(id=3)
    api.find_project.return_value = record(id=9, enabled=True, owner_group=None)
    api.get_project_datasets.return_value = [record(dataset=record(id=4))]
    api.get_project_trigger_repositories.return_value = [
        record(trigger_repository=record(id=2), watch_dir="specs", base_branch="main", enabled=True),
    ]
    api.get_project_results_repositories.return_value = [
        record(results_repository=record(id=3), target_dir="results", base_branch="main", enabled=True),
    ]

    result = sync.sync_project(api, "cohort", PROJECT)

    api.patch_project.assert_not_called()
    assert not result.changed


def test_live_project_unassigns_what_the_spec_dropped(api):
    api.find_dataset.return_value = record(id=4)
    api.find_trigger_repository.return_value = record(id=2)
    api.find_results_repository.return_value = record(id=3)
    api.find_project.return_value = record(id=9, enabled=True, owner_group="service")
    api.get_project_datasets.return_value = [record(dataset=record(id=4)), record(dataset=record(id=6))]
    api.get_project_trigger_repositories.return_value = [
        record(trigger_repository=record(id=2), watch_dir="specs", base_branch="main", enabled=True),
        record(trigger_repository=record(id=8), watch_dir="specs", base_branch="main", enabled=True),
    ]
    api.get_project_results_repositories.return_value = [
        record(results_repository=record(id=3), target_dir="results", base_branch="main", enabled=True),
    ]

    result = sync.sync_project(api, "cohort", PROJECT)

    api.delete_project_dataset.assert_called_once_with(9, 6)
    api.delete_project_trigger_repository.assert_called_once_with(9, 8)
    api.get_or_assign_dataset.assert_not_called()
    api.put_project_trigger_repository.assert_not_called()
    assert result.changed


def test_delete_never_forces(api):
    api.find_project.return_value = record(id=9)
    sync.delete_project(api, "cohort", PROJECT)
    api.delete_project.assert_called_once_with(9)
