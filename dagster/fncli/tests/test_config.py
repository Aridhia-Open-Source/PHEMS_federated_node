import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import click
import pytest
from pydantic import ValidationError

from fncli.cmds import common
from fncli.cmds.common import (
    DatasetConfig,
    GiteaConfig,
    RepoConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    build_researcher_git_api,
    build_git_api,
    get_repository,
    to_host_url,
)
from app.config import EnvConfig
from app.gitea import GiteaAPI
from app.github import GithubAPI
from app.models import GitToken, ResultsRepository, TriggerRepository
from app.tests.conftest import SAMPLE_PROVIDER, SAMPLE_TRIGGER_REPOSITORY


def test_gitea_config_defaults_to_the_port_forwarded_address(monkeypatch):
    monkeypatch.delenv("GITEA_URL", raising=False)

    assert GiteaConfig().gitea_host_api_uri == "http://localhost:4000/api/v1"


def test_gitea_config_reaches_an_in_cluster_url_through_localhost(monkeypatch):
    monkeypatch.setenv("GITEA_URL", "http://gitea.fn.svc:4000")

    assert GiteaConfig().gitea_host_api_uri == "http://localhost:4000/api/v1"


@pytest.mark.parametrize("url, expected", [
    ("http://gitea.fn.svc:4000/api/v1", "http://localhost:4000/api/v1"),
    ("https://gitea.fn.svc/org/repo.git", "https://localhost/org/repo.git"),
    ("http://localhost:4000/api/v1", "http://localhost:4000/api/v1"),
    ("https://api.github.com", "https://api.github.com"),
])
def test_to_host_url_only_swaps_an_in_cluster_hostname(url, expected):
    assert to_host_url(url) == expected


def test_the_provider_uri_is_the_api_scheme_and_the_repo_host(monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO_URI", "Gitea.fn.svc:4000/gitea_admin/trigger.git")
    monkeypatch.setenv("GITEA_API_URI", "http://gitea.fn.svc:4000/api/v1")

    assert TriggerRepoConfig().provider_uri == "http://gitea.fn.svc:4000"


def test_values_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO", "other")
    monkeypatch.setenv("TEST_TRIGGER_REPO_WATCH_DIR", "tasks/")

    config = TriggerRepoConfig()

    assert (config.repo, config.watch_dir) == ("other", "tasks/")


@pytest.mark.parametrize("config_class, field", [
    (TriggerRepoConfig, "TEST_TRIGGER_REPO"),
    (ResultsRepoConfig, "TEST_RESULTS_REPO"),
    (DatasetConfig, "DEFAULT_PROJECT_DATASET"),
])
def test_an_empty_value_is_rejected(monkeypatch, config_class, field):
    monkeypatch.setenv(field, "")

    with pytest.raises(ValidationError, match="required"):
        config_class()


def test_env_config_rejects_an_empty_field_given_directly():
    class Config(EnvConfig):
        name: str = "x"

    with pytest.raises(ValidationError):
        Config(name="")


def test_secret_label_defaults_to_the_repo_name_with_creds():
    assert TriggerRepoConfig().secret_label == "trigger-creds"


def test_secret_label_prefers_the_backend_record():
    config = TriggerRepoConfig(backend_secret_label="from-backend")

    assert config.secret_label == "from-backend"


def test_dataset_secret_label_is_derived_from_the_dataset():
    assert DatasetConfig().secret_label == "cdm-dataset-creds"


def test_repo_config_is_abstract_about_the_token_scope():
    assert "token_scope" not in vars(RepoConfig)


# The provider and the repo's API client

def test_a_github_com_repo_uri_is_a_github_repo(monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO_URI", "https://GitHub.com/aridhia/trigger.git")

    config = TriggerRepoConfig()

    assert (config.git_provider, config.is_github) == ("github", True)


def test_any_other_repo_uri_is_a_gitea_repo():
    config = TriggerRepoConfig()

    assert (config.git_provider, config.is_github) == ("gitea", False)


def test_the_backend_records_provider_type_wins_over_the_repo_uri():
    config = TriggerRepoConfig(backend_provider_type="github")

    assert config.is_github


def test_the_provider_is_not_an_env_var(monkeypatch):
    monkeypatch.setenv("TEST_GIT_PROVIDER", "github")
    monkeypatch.setenv("GH_TOKEN", "ghp_x")

    assert not TriggerRepoConfig().is_github


def test_each_repo_config_knows_its_entity():
    assert (TriggerRepoConfig.entity, ResultsRepoConfig.entity) == ("trigger", "results")


def test_get_repository_finds_the_global_record_of_the_repo_uri():
    backend_api = MagicMock()

    repository = get_repository(ResultsRepoConfig(), backend_api)

    backend_api.find_results_repository.assert_called_once_with("http://gitea.fn.svc:3000/gitea_admin/results")
    assert repository is backend_api.find_results_repository.return_value


def test_get_repository_names_the_command_that_registers_a_missing_repository():
    backend_api = MagicMock()
    backend_api.find_trigger_repository.return_value = None

    with pytest.raises(click.ClickException, match="fncli apply"):
        get_repository(TriggerRepoConfig(), backend_api)


def gitea_repository(cls=TriggerRepository):
    provider = {**SAMPLE_PROVIDER, "type": "gitea", "uri": "http://gitea.fn.svc:3000", "api_uri": "http://gitea.fn.svc:3000/api/v1"}
    return cls(**{**SAMPLE_TRIGGER_REPOSITORY, "provider": provider})


@pytest.fixture
def backend_api(monkeypatch):
    api = MagicMock()
    api.get_repository_token.return_value = GitToken(token="minted", expires_at="2026-01-01T01:00:00Z")
    monkeypatch.setattr(common, "build_backend_api", lambda config: api)
    return api


def test_the_git_api_of_a_gitea_repo_is_a_token_client_through_the_port_forward(backend_api):
    backend_api.find_trigger_repository.return_value = gitea_repository()

    git_api = build_git_api(TriggerRepoConfig())

    assert isinstance(git_api, GiteaAPI)
    assert git_api.client._base_uri == "http://localhost:3000/api/v1"
    assert git_api.client.token == "minted"
    backend_api.get_repository_token.assert_called_once_with("trigger", 1, None)


def test_the_git_api_of_a_results_repo_gets_a_results_token(backend_api):
    backend_api.find_results_repository.return_value = gitea_repository(ResultsRepository)

    build_git_api(ResultsRepoConfig())

    backend_api.get_repository_token.assert_called_once_with("results", 1, None)


def test_the_git_api_of_a_github_repo_is_a_github_client(backend_api):
    backend_api.find_trigger_repository.return_value = TriggerRepository(**SAMPLE_TRIGGER_REPOSITORY)

    git_api = build_git_api(TriggerRepoConfig())

    assert isinstance(git_api, GithubAPI)
    assert git_api.client._base_uri == "https://api.github.com"


# The researcher's writes to the trigger repo

@pytest.fixture
def github_trigger(monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO_URI", "https://github.com/aridhia/trigger")
    monkeypatch.delenv("RESEARCHER_GIT_TOKEN", raising=False)


def test_the_researcher_writes_to_a_gitea_repo_as_the_gitea_admin(monkeypatch):
    monkeypatch.setattr(common, "build_gitea_api", lambda config: "admin api")

    assert build_researcher_git_api(TriggerRepoConfig()) == "admin api"


def test_the_researcher_writes_to_a_github_repo_with_researcher_git_token(monkeypatch, github_trigger):
    monkeypatch.setenv("RESEARCHER_GIT_TOKEN", "ghp_mine")
    monkeypatch.setattr(common.subprocess, "run", lambda *args, **kwargs: pytest.fail("gh is only the fallback"))

    git_api = build_researcher_git_api(TriggerRepoConfig())

    assert isinstance(git_api, GithubAPI)
    assert git_api.client.token == "ghp_mine"


def test_without_researcher_git_token_the_researcher_uses_the_gh_cli_token(monkeypatch, github_trigger):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="gho_cli\n")

    monkeypatch.setattr(common.subprocess, "run", run)

    git_api = build_researcher_git_api(TriggerRepoConfig())

    assert calls == [["gh", "auth", "token"]]
    assert git_api.client.token == "gho_cli"


@pytest.mark.parametrize("failure", [FileNotFoundError("gh"), subprocess.CalledProcessError(1, "gh")])
def test_a_github_write_with_neither_token_fails_and_says_what_to_set(monkeypatch, github_trigger, failure):
    def run(command, **kwargs):
        raise failure

    monkeypatch.setattr(common.subprocess, "run", run)

    with pytest.raises(click.ClickException, match="RESEARCHER_GIT_TOKEN"):
        build_researcher_git_api(TriggerRepoConfig())
