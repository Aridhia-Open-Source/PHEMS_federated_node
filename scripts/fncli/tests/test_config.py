import pytest
from pydantic import ValidationError

from fncli.cmds.common import (
    DatasetConfig,
    GiteaConfig,
    RepoConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    to_host_url,
)
from fncli.dagster.config import EnvConfig


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


def test_dataset_config_defaults_to_the_dummy_dataset():
    config = DatasetConfig()

    assert (config.dataset_host, config.dataset_port, config.dataset_type) == (
        "db-datasets.fn.svc", 5432, "postgres",
    )
    assert (config.dataset_read_schema, config.dataset_write_schema) == ("cdm", "results")
    assert (config.dataset_username, config.dataset_password) == ("dummy", "dummy")


def test_dataset_config_takes_the_uc1_values_from_the_env(monkeypatch):
    for key, value in {
        "CLUSTER_DATASET_HOST": "db-datasets-uc1.fn.svc",
        "DATASET_PORT": "5433",
        "DATASET_TYPE": "mssql",
        "DATASET_SCHEMA": "omop",
        "DATASET_SCHEMA_WRITE": "omop_results",
        "DATASET_USERNAME": "uc1",
        "DATASET_PASSWORD": "s3cret",
    }.items():
        monkeypatch.setenv(key, value)

    config = DatasetConfig()

    assert (config.dataset_host, config.dataset_port, config.dataset_type) == (
        "db-datasets-uc1.fn.svc", 5433, "mssql",
    )
    assert (config.dataset_read_schema, config.dataset_write_schema) == ("omop", "omop_results")
    assert (config.dataset_username, config.dataset_password) == ("uc1", "s3cret")
