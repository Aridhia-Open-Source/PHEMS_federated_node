import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner

from fncli.cmds import repository
from fncli.cmds.common import ResultsRepoConfig, TriggerRepoConfig, get_base_branch

PROJECT = SimpleNamespace(id=7)


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_or_create_trigger_repository.return_value = SimpleNamespace(
        id=1, uri="u", provider=SimpleNamespace(name="p", api_uri="a"), secret=SimpleNamespace(label="l"),
    )
    return api


def test_the_trigger_repo_is_assigned_with_the_given_base_branch(backend_api):
    repository.init_backend_trigger_repo(TriggerRepoConfig(), backend_api, PROJECT, "release")

    assert backend_api.get_or_assign_repository.call_args.kwargs["base_branch"] == "release"


def test_the_results_repo_is_assigned_with_the_given_base_branch(backend_api):
    repository.init_backend_results_repo(ResultsRepoConfig(), backend_api, PROJECT, "release")

    assert backend_api.get_or_assign_results_repository.call_args.args[-1] == "release"


def test_the_base_branch_option_wins_over_the_env_var(monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO_BASE_BRANCH", "from-env")

    assert get_base_branch(TriggerRepoConfig(), "from-option") == "from-option"
    assert get_base_branch(TriggerRepoConfig()) == "from-env"


@pytest.mark.parametrize("config_class, variable", [
    (TriggerRepoConfig, "TEST_TRIGGER_REPO_BASE_BRANCH"), (ResultsRepoConfig, "TEST_RESULTS_REPO_BASE_BRANCH"),
])
def test_no_base_branch_is_an_error_that_names_the_env_var(monkeypatch, config_class, variable):
    monkeypatch.delenv(variable, raising=False)

    with pytest.raises(click.ClickException, match=variable):
        get_base_branch(config_class())


def test_init_backend_trigger_repo_fails_before_the_backend_without_a_base_branch(monkeypatch):
    monkeypatch.delenv("TEST_TRIGGER_REPO_BASE_BRANCH", raising=False)
    monkeypatch.setattr(repository, "build_backend_api", lambda config: pytest.fail("no base branch, no backend"))

    result = CliRunner().invoke(repository.init_backend_trigger_repo_command, [])

    assert result.exit_code == 1
    assert "TEST_TRIGGER_REPO_BASE_BRANCH" in result.output


def test_init_gitea_repo_does_nothing_for_a_github_repo(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="repository")
    monkeypatch.setenv("TEST_TRIGGER_REPO_URI", "https://github.com/aridhia/trigger")
    monkeypatch.setattr(repository, "build_gitea_api", lambda config: pytest.fail("a GitHub repo has no Gitea admin"))

    result = CliRunner().invoke(repository.init_gitea_repo_command, [])

    assert result.exit_code == 0, result.output
    assert "Not creating GitHub repo aridhia/trigger" in caplog.text
