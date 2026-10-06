import pytest
from pydantic import ValidationError

from fncli.cmds.common import (
    DatasetConfig,
    GiteaConfig,
    RepoConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
)
from fncli.dagster.config import EnvConfig


def test_gitea_config_defaults_to_the_port_forwarded_address(monkeypatch):
    monkeypatch.delenv("GITEA_URL", raising=False)

    assert GiteaConfig().gitea_host_api_uri == "http://localhost:4000/api/v1"


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


def test_dataset_secret_label_is_derived_from_the_project():
    assert DatasetConfig().secret_label == "proj-dataset-creds"


def test_repo_config_is_abstract_about_the_token_scope():
    assert "token_scope" not in vars(RepoConfig)
