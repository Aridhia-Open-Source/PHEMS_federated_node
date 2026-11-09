from types import SimpleNamespace
from unittest.mock import MagicMock

import click
import pytest

from fncli.cmds import repository
from fncli.tests.conftest import NODE, results_config, trigger_config

PROJECT = SimpleNamespace(id=7)


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_or_create_trigger_repository.return_value = SimpleNamespace(
        id=1, uri="u", provider=SimpleNamespace(name="p", api_uri="a"), secret=SimpleNamespace(label="l"),
    )
    return api


def test_the_trigger_repo_is_assigned_with_the_given_base_branch(backend_api):
    repository.init_backend_trigger_repo(trigger_config(), backend_api, PROJECT, "release")

    assert backend_api.get_or_assign_repository.call_args.kwargs["base_branch"] == "release"


def test_the_results_repo_is_assigned_with_the_given_base_branch(backend_api):
    repository.init_backend_results_repo(results_config(), backend_api, PROJECT, "release")

    assert backend_api.get_or_assign_results_repository.call_args.args[-1] == "release"


# The config of a project's repository, read from the node

def trigger_record(owner="gitea_admin"):
    """A project's trigger repository assignment, as the backend returns it"""
    trigger = SimpleNamespace(
        uri=f"gitea.fn.svc:4000/{owner}/trigger-x",
        provider=SimpleNamespace(uri="http://gitea.fn.svc:4000", api_uri="http://gitea.fn.svc:4000/api/v1", type="gitea"),
        secret=SimpleNamespace(label="trigger-x-creds"),
    )
    return SimpleNamespace(trigger_repository=trigger, watch_dir="specs/", base_branch="release")


def node_with(record, project=SimpleNamespace(id=3, name="demo")):
    api = MagicMock()
    api.find_project.return_value = project
    api.get_project_trigger_repositories.return_value = [record]
    return api


def test_a_repo_config_is_the_projects_record_on_the_node_with_no_env():
    config = repository.load_repo_config("trigger", SimpleNamespace(node=NODE), "demo", node_with(trigger_record()))

    assert (config.project_name, config.repo, config.watch_dir, config.base_branch) == ("demo", "trigger-x", "specs/", "release")
    assert (config.gitea_url, config.gitea_api_uri) == ("http://gitea.fn.svc:4000", "http://gitea.fn.svc:4000/api/v1")
    assert (config.secret_label, config.git_provider, config.node) == ("trigger-x-creds", "gitea", NODE)


def test_a_gitea_repo_that_is_not_the_admin_users_is_refused():
    with pytest.raises(click.ClickException, match="owned by someone-else, not the Gitea admin user gitea_admin"):
        repository.load_repo_config(
            "trigger", SimpleNamespace(node=NODE), "demo", node_with(trigger_record(owner="someone-else"))
        )


def test_a_project_that_is_not_on_the_node_says_to_apply_it():
    with pytest.raises(click.ClickException, match="fncli apply"):
        repository.load_repo_config("trigger", SimpleNamespace(node=NODE), "demo", node_with(trigger_record(), project=None))
