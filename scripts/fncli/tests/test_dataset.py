from unittest.mock import MagicMock

from fncli.cmds.common import DatasetConfig
from fncli.cmds.dataset import init_backend_dataset
from fncli.cmds.secret import init_backend_secret, init_dataset_secret

UC1_ENV = {
    "CLUSTER_DATASET_HOST": "db-datasets-uc1.fn.svc",
    "DATASET_PORT": "5433",
    "DATASET_TYPE": "postgres",
    "DATASET_SCHEMA": "omop",
    "DATASET_SCHEMA_WRITE": "omop_results",
    "DATASET_USERNAME": "uc1",
    "DATASET_PASSWORD": "s3cret",
}


def uc1_config(monkeypatch):
    for key, value in UC1_ENV.items():
        monkeypatch.setenv(key, value)
    return DatasetConfig()


def test_init_backend_dataset_registers_the_configured_dataset(monkeypatch):
    backend_api = MagicMock()
    project = MagicMock(id=7)

    init_backend_dataset(uc1_config(monkeypatch), backend_api, project)

    assert backend_api.get_or_create_dataset.call_args.args == ("cdm",)
    assert backend_api.get_or_create_dataset.call_args.kwargs == {
        "host": "db-datasets-uc1.fn.svc",
        "port": 5433,
        "db_type": "postgres",
        "secret_label": "proj-dataset-creds",
        "read_schema": "omop",
        "write_schema": "omop_results",
    }
    backend_api.get_or_assign_dataset.assert_called_once_with(
        7, backend_api.get_or_create_dataset.return_value
    )


def test_init_dataset_secret_stores_the_configured_credentials(monkeypatch):
    backend_api = MagicMock()
    project = MagicMock(id=7)

    init_dataset_secret(uc1_config(monkeypatch), backend_api, project)

    backend_api.upsert_secret.assert_called_once_with(
        "proj-dataset-creds", {"USERNAME": "uc1", "PASSWORD": "s3cret"}
    )


def test_init_dataset_secret_stores_dummies_without_the_env():
    backend_api = MagicMock()

    init_dataset_secret(DatasetConfig(), backend_api, MagicMock(id=7))

    backend_api.upsert_secret.assert_called_once_with(
        "proj-dataset-creds", {"USERNAME": "dummy", "PASSWORD": "dummy"}
    )


def test_init_backend_secret_keeps_an_existing_dataset_secret(monkeypatch):
    backend_api = MagicMock()
    backend_api.get_secrets.return_value = [{"label": "proj-dataset-creds"}]

    init_backend_secret(uc1_config(monkeypatch), backend_api, MagicMock(id=7))

    backend_api.upsert_secret.assert_not_called()
