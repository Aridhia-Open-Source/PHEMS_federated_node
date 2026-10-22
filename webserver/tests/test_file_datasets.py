"""
File based datasets (duckdb, sqlite): API validation, and the task pod
they produce
"""
from kubernetes.client.exceptions import ApiException
from pytest import fixture, mark
from unittest.mock import Mock

from app.helpers.const import DATASET_MOUNT_PATH
from app.helpers.base_model import db
from app.models.dataset import Dataset
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


@fixture
def pvc_mock(mocker):
    return mocker.patch(
        'app.helpers.kubernetes.KubernetesClient.read_namespaced_persistent_volume_claim',
        return_value=Mock(metadata=Mock(annotations={}))
    )


@fixture
def file_ds_body():
    return {
        "name": "clinic-duckdb",
        "type": "duckdb",
        "volume_claim": "clinic-files",
        "path": "clinic.duckdb"
    }


@fixture
def duckdb_dataset(client, user_uuid, k8s_client, file_ds_body) -> Dataset:
    ds = Dataset(**file_ds_body)
    ds.add(user_id=user_uuid)
    return ds


class TestPostFileDataset:
    def test_post_duckdb_dataset(
            self, client, post_json_admin_header, simple_admin_header, k8s_client, file_ds_body
        ):
        """
        A file based dataset needs no host or credentials, and keeps no secret
        """
        response = client.post("/datasets/", json=file_ds_body, headers=post_json_admin_header)
        assert response.status_code == 201, response.json

        ds = Dataset.query.filter(Dataset.name == "clinic-duckdb").one()
        assert ds.host is None
        assert ds.port is None
        assert ds.schema == "main"
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

        response = client.get(f"/datasets/{ds.id}", headers=simple_admin_header)
        assert response.json["volume_claim"] == "clinic-files"
        assert response.json["path"] == "clinic.duckdb"

    def test_post_sqlite_dataset(self, client, post_json_admin_header, file_ds_body):
        file_ds_body["type"] = "sqlite"
        file_ds_body["path"] = "nested/clinic.sqlite"
        response = client.post("/datasets/", json=file_ds_body, headers=post_json_admin_header)
        assert response.status_code == 201, response.json

    @mark.parametrize("changes, error", [
        ({"volume_claim": None}, "volume_claim is required"),
        ({"path": None}, "path is required"),
        ({"path": "/abs/clinic.duckdb"}, "path must be relative and can't contain '..'"),
        ({"path": "data/../../clinic.duckdb"}, "path must be relative and can't contain '..'"),
        ({"host": "db"}, "host not allowed for duckdb datasets"),
        ({"port": 5432}, "port not allowed for duckdb datasets"),
        ({"username": "a", "password": "b"}, "username, password not allowed for duckdb datasets"),
        ({"schema_write": "out"}, "schema_write not allowed for duckdb datasets"),
    ])
    def test_post_file_dataset_invalid(
            self, client, post_json_admin_header, file_ds_body, changes, error
        ):
        file_ds_body.update(changes)
        response = client.post("/datasets/", json=file_ds_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert response.json["error"] == error
        assert Dataset.query.count() == 0

    @mark.parametrize("changes, error", [
        ({"volume_claim": "c", "path": "x.db"}, "volume_claim, path not allowed for postgres datasets"),
        ({"host": None}, "host is required"),
        ({"password": None}, "username and password are required"),
    ])
    def test_post_server_dataset_invalid(
            self, client, post_json_admin_header, dataset_post_body, changes, error
        ):
        """
        Server engines behave as before, and missing credentials are a 400
        """
        dataset_post_body.update(changes)
        response = client.post("/datasets/", json=dataset_post_body, headers=post_json_admin_header)
        assert response.status_code == 400
        assert response.json["error"] == error


class TestPatchFileDataset:
    def test_patch_path(self, client, post_json_admin_header, k8s_client, duckdb_dataset):
        response = client.patch(
            f"/datasets/{duckdb_dataset.id}",
            json={"path": "v2/clinic.duckdb"},
            headers=post_json_admin_header
        )
        assert response.status_code == 202, response.json
        assert db.session.get(Dataset, duckdb_dataset.id).path == "v2/clinic.duckdb"
        k8s_client["read_namespaced_secret_mock"].assert_not_called()
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_patch_name(self, client, post_json_admin_header, k8s_client, duckdb_dataset):
        response = client.patch(
            f"/datasets/{duckdb_dataset.id}",
            json={"name": "clinic-v2"},
            headers=post_json_admin_header
        )
        assert response.status_code == 202, response.json
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_patch_to_sqlite(self, client, post_json_admin_header, duckdb_dataset):
        response = client.patch(
            f"/datasets/{duckdb_dataset.id}",
            json={"type": "sqlite", "path": "clinic.sqlite"},
            headers=post_json_admin_header
        )
        assert response.status_code == 202, response.json

    @mark.parametrize("changes, error", [
        ({"type": "postgres"}, "type can't change between file based and server engines"),
        ({"host": "db"}, "host not allowed for duckdb datasets"),
        ({"password": "b"}, "password not allowed for duckdb datasets"),
        ({"path": "../x"}, "path must be relative and can't contain '..'"),
        ({"volume_claim": None}, "volume_claim is required"),
    ])
    def test_patch_invalid(
            self, client, post_json_admin_header, duckdb_dataset, changes, error
        ):
        response = client.patch(
            f"/datasets/{duckdb_dataset.id}", json=changes, headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == error

    def test_patch_server_to_file_type_fails(self, client, post_json_admin_header, dataset):
        response = client.patch(
            f"/datasets/{dataset.id}", json={"type": "duckdb"}, headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "type can't change between file based and server engines"

    def test_patch_server_dataset_rejects_file_fields(self, client, post_json_admin_header, dataset):
        response = client.patch(
            f"/datasets/{dataset.id}", json={"path": "x.db"}, headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "path not allowed for postgres datasets"


class TestDeleteFileDataset:
    def test_delete(self, client, post_json_admin_header, k8s_client, duckdb_dataset):
        """
        There's no secret, and a 404 on its deletion is already tolerated
        """
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=404)
        response = client.delete(f"/datasets/{duckdb_dataset.id}", headers=post_json_admin_header)
        assert response.status_code == 204
        assert Dataset.query.count() == 0


class TestFileDatasetModel:
    def test_connection_strings(self, duckdb_dataset):
        assert duckdb_dataset.get_connection_string() == (
            f"driver={{DuckDB Driver}};Database={DATASET_MOUNT_PATH}/clinic.duckdb;access_mode=read_only;"
        )
        duckdb_dataset.type = "sqlite"
        duckdb_dataset.extra_connection_args = "NoTXN=1"
        assert duckdb_dataset.get_connection_string() == (
            f"driver={{SQLite3}};Database=file:{DATASET_MOUNT_PATH}/clinic.duckdb?mode=ro&immutable=1;NoTXN=1"
        )

    def test_secret_name_unchanged_for_server_datasets(self, dataset):
        assert dataset.get_creds_secret_name() == "example.com-testds-creds"


class TestFileDatasetTasks:
    def post_task(self, client, headers, task_body, dataset, code=201):
        task_body.pop("db_query")
        task_body["tags"]["dataset_id"] = dataset.id
        response = client.post('/tasks/', json=task_body, headers=headers)
        assert response.status_code == code, response.json
        return response

    def test_task_pod(
            self, cr_client, post_json_admin_header, client, reg_k8s_client,
            registry_client, task_body, pvc_mock, duckdb_dataset
        ):
        """
        The PVC is mounted read-only, db-liveness is skipped, and the env
        points at the file rather than a server
        """
        self.post_task(client, post_json_admin_header, task_body, duckdb_dataset)
        pod = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]

        assert [c.name for c in pod.spec.init_containers] == ["init-1"]
        volumes = {v.name: v for v in pod.spec.volumes}
        assert volumes["dataset"].persistent_volume_claim.claim_name == "clinic-files"
        assert volumes["dataset"].persistent_volume_claim.read_only is True

        container = pod.spec.containers[0]
        mount = [m for m in container.volume_mounts if m.name == "dataset"][0]
        assert mount.mount_path == DATASET_MOUNT_PATH
        assert mount.read_only is True

        env = {e.name: e.value for e in container.env}
        assert env["DATASET_TYPE"] == "duckdb"
        assert env["DATASET_PATH"] == f"{DATASET_MOUNT_PATH}/clinic.duckdb"
        assert env["CDM_SCHEMA"] == "main"
        assert "Database=/mnt/dataset/clinic.duckdb" in env["CONNECTION_STRING"]
        assert "WRITE_SCHEMA" not in env
        assert "ORACLE_SID" not in env
        assert pod.metadata.annotations is None
        assert pod.spec.security_context is None

    def test_missing_claim(
            self, cr_client, post_json_admin_header, client, reg_k8s_client,
            registry_client, task_body, pvc_mock, duckdb_dataset
        ):
        pvc_mock.side_effect = ApiException(status=404, reason="Not Found")
        response = self.post_task(client, post_json_admin_header, task_body, duckdb_dataset, code=400)
        assert response.json["error"] == "Volume claim clinic-files for dataset clinic-duckdb not found"
        reg_k8s_client["create_namespaced_pod_mock"].assert_not_called()
