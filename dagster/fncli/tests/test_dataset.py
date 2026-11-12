from unittest.mock import MagicMock

from fncli.cmds.common import DatasetConfig
from fncli.cmds.dataset import init_backend_dataset
from fncli.cmds.secret import init_backend_secret, init_dataset_secret

STUDY_ENV = {
    "CLUSTER_DATASET_HOST": "db-datasets-study.fn.svc",
    "DATASET_PORT": "5433",
    "DATASET_TYPE": "postgres",
    "DATASET_SCHEMA": "omop",
    "DATASET_SCHEMA_WRITE": "omop_results",
    "DATASET_USERNAME": "study",
    "DATASET_PASSWORD": "s3cret",
}


def study_config(monkeypatch):
    for key, value in STUDY_ENV.items():
        monkeypatch.setenv(key, value)
    return DatasetConfig()


def test_init_backend_dataset_registers_the_configured_dataset(monkeypatch):
    backend_api = MagicMock()
    project = MagicMock(id=7)

    init_backend_dataset(study_config(monkeypatch), backend_api, project)

    assert backend_api.get_or_create_dataset.call_args.args == ("cdm",)
    assert backend_api.get_or_create_dataset.call_args.kwargs == {
        "host": "db-datasets-study.fn.svc",
        "port": 5433,
        "db_type": "postgres",
        "secret_label": "cdm-dataset-creds",
        "read_schema": "omop",
        "write_schema": "omop_results",
    }
    backend_api.get_or_assign_dataset.assert_called_once_with(
        7, backend_api.get_or_create_dataset.return_value
    )


def test_init_dataset_secret_stores_the_configured_credentials(monkeypatch):
    backend_api = MagicMock()

    init_dataset_secret(study_config(monkeypatch), backend_api)

    backend_api.upsert_secret.assert_called_once_with(
        "cdm-dataset-creds", {"USERNAME": "study", "PASSWORD": "s3cret"}
    )


def test_init_dataset_secret_stores_dummies_without_the_env():
    backend_api = MagicMock()

    init_dataset_secret(DatasetConfig(), backend_api)

    backend_api.upsert_secret.assert_called_once_with(
        "cdm-dataset-creds", {"USERNAME": "dummy", "PASSWORD": "dummy"}
    )


def test_init_backend_secret_keeps_an_existing_dataset_secret(monkeypatch):
    backend_api = MagicMock()
    backend_api.get_secrets.return_value = [{"label": "cdm-dataset-creds"}]

    init_backend_secret(study_config(monkeypatch), backend_api)

    backend_api.upsert_secret.assert_not_called()
