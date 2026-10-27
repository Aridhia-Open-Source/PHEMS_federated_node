import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from app.definitions import pipes
from app.secrets import K8sSecretProvider
from app.definitions.pipes import (
    K8sPipe,
    K8sPipesResponse,
    TERMINATION_GRACE_PERIOD_SECONDS,
    _dict_to_pod_env,
)


PIPES_ENV = {
    "DAGSTER_DEPLOYMENT_NAMESPACE": "fn",
    "DAGSTER_TASK_NAMESPACE": "tasks",
    "DAGSTER_ARTIFACTS_PVC_NAME": "artifacts-pvc",
    "DAGSTER_ARTIFACT_MOUNT_PATH": "/mnt/dagster/artifacts",
    "DAGSTER_TASK_ACTIVE_DEADLINE_SECONDS": "21600",
}

SECURITY_CONTEXT_ENV = (
    "DAGSTER_PIPES_FS_GROUP",
    "DAGSTER_PIPES_RUN_AS_USER",
    "DAGSTER_PIPES_RUN_AS_GROUP",
    "DAGSTER_PIPES_SUPPLEMENTAL_GROUPS",
)

DATASET_CONFIG = {
    "dataset": {
        "name": "cdm",
        "host": "db.host",
        "port": 5432,
        "type": "postgres",
        "read_schema": "cdm_schema",
        "write_schema": "results",
        "secret": {"provider": "K8S", "key": "db-host-cdm-creds", "namespace": "fn"},
    }
}


@pytest.fixture
def pipes_env(monkeypatch):
    for key, value in PIPES_ENV.items():
        monkeypatch.setenv(key, value)
    for key in SECURITY_CONTEXT_ENV:
        monkeypatch.delenv(key, raising=False)


def make_pipe(client=None, ext_env=None, **config):
    context = MagicMock()
    context.run_id = "run-1"
    context.run.tags = {"task_id": "7"}
    context.op_config = {"docker_image": "ghcr.io/org/experiment:latest", **config}
    return K8sPipe(client=client or MagicMock(), context=context, ext_env=ext_env)


class TestBasePodSpec:
    def test_task_pod_gets_no_service_account_token(self, pipes_env):
        spec = make_pipe()._build_base_pod_spec()

        assert spec["automountServiceAccountToken"] is False
        assert "serviceAccountName" not in spec

    def test_pod_defaults(self, pipes_env):
        spec = make_pipe()._build_base_pod_spec()

        assert spec["restartPolicy"] == "Never"
        assert spec["terminationGracePeriodSeconds"] == TERMINATION_GRACE_PERIOD_SECONDS
        assert spec["containers"][0]["imagePullPolicy"] == "Always"

    def test_no_image_pull_secrets_without_one_configured(self, pipes_env):
        assert "imagePullSecrets" not in make_pipe()._build_base_pod_spec()

    def test_image_pull_secrets_from_config(self, pipes_env):
        spec = make_pipe(image_pull_secret="ghcr-io")._build_base_pod_spec()

        assert spec["imagePullSecrets"] == [{"name": "ghcr-io"}]

    def test_no_security_context_when_unset(self, pipes_env):
        assert "securityContext" not in make_pipe()._build_base_pod_spec()

    def test_security_context_from_env(self, pipes_env, monkeypatch):
        monkeypatch.setenv("DAGSTER_PIPES_RUN_AS_USER", "1001")
        monkeypatch.setenv("DAGSTER_PIPES_FS_GROUP", "2001")

        spec = make_pipe()._build_base_pod_spec()

        assert spec["securityContext"] == {"fsGroup": 2001, "runAsUser": 1001}

    def test_volume_is_the_artifacts_claim_mounted_at_the_runs_folder_only(self, pipes_env):
        spec = make_pipe()._build_base_pod_spec()

        assert spec["volumes"] == [{
            "name": "artifacts-pvc",
            "persistentVolumeClaim": {"claimName": "artifacts-pvc"},
        }]
        assert spec["containers"][0]["volumeMounts"] == [{
            "name": "artifacts-pvc",
            "mountPath": "/mnt/dagster/artifacts/run-1",
            "subPath": "run-1",
        }]

    def test_pod_is_killed_at_its_deadline(self, pipes_env):
        assert make_pipe()._build_base_pod_spec()["activeDeadlineSeconds"] == 21600

    def test_missing_deadline_is_not_defaulted(self, pipes_env, monkeypatch):
        monkeypatch.delenv("DAGSTER_TASK_ACTIVE_DEADLINE_SECONDS")

        with pytest.raises(KeyError):
            make_pipe()

    def test_container_is_locked_down(self, pipes_env):
        container = make_pipe()._build_base_pod_spec()["containers"][0]

        assert container["securityContext"] == {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
            "runAsNonRoot": True,
        }

    def test_no_resources_unless_the_spec_has_some(self, pipes_env):
        assert "resources" not in make_pipe()._build_base_pod_spec()["containers"][0]
        assert "resources" not in make_pipe(resources={})._build_base_pod_spec()["containers"][0]

    def test_spec_resources_are_the_containers(self, pipes_env):
        resources = {"limits": {"cpu": "1", "memory": "2Gi"}, "requests": {"cpu": "100m", "memory": "512Mi"}}

        container = make_pipe(resources=resources)._build_base_pod_spec()["containers"][0]

        assert container["resources"] == resources

    def test_container_is_named_for_the_run(self, pipes_env):
        spec = make_pipe()._build_base_pod_spec()

        assert spec["containers"][0]["name"] == "pipes-run-1"

    def test_a_dataset_task_has_its_limits_hardening_run_folder_and_secret_env_together(self, pipes_env):
        resources = {"limits": {"cpu": "1", "memory": "2Gi"}}

        spec = make_pipe(resources=resources, **DATASET_CONFIG)._build_base_pod_spec()

        container = spec["containers"][0]
        names = [e["name"] for e in container["env"]]
        assert container["resources"] == resources
        assert container["securityContext"]["runAsNonRoot"] is True
        assert spec["activeDeadlineSeconds"] == 21600
        assert container["volumeMounts"][0]["subPath"] == "run-1"
        assert container["env"][names.index("DB_PASSWORD")]["valueFrom"]["secretKeyRef"] == {
            "name": "task-7", "key": "PASSWORD"
        }
        assert names[-3:] == ["DB_USERNAME", "DB_PASSWORD", "CONNECTION_STRING"]


class TestNamespaces:
    def test_task_pods_run_in_the_tasks_namespace(self, pipes_env):
        pipe = make_pipe()

        assert pipe.namespace == "fn"
        assert pipe.task_namespace == "tasks"

    def test_task_namespace_falls_back_to_the_deployment_one(self, pipes_env, monkeypatch):
        monkeypatch.delenv("DAGSTER_TASK_NAMESPACE")

        assert make_pipe().task_namespace == "fn"

    def test_empty_task_namespace_falls_back_to_the_deployment_one(self, pipes_env, monkeypatch):
        monkeypatch.setenv("DAGSTER_TASK_NAMESPACE", "")

        assert make_pipe().task_namespace == "fn"

    def test_missing_required_env_is_not_defaulted(self, pipes_env, monkeypatch):
        monkeypatch.delenv("DAGSTER_ARTIFACTS_PVC_NAME")

        with pytest.raises(KeyError):
            make_pipe()


class TestDatasetConfig:
    def test_no_dataset_configured(self, pipes_env):
        pipe = make_pipe()

        assert pipe.dataset == {}
        assert "CDM_SCHEMA" not in pipe.env

    def test_dataset_config_is_used_as_given(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)

        assert pipe.dataset == DATASET_CONFIG["dataset"]

    def test_incomplete_dataset_is_rejected(self, pipes_env):
        config = {"dataset": {**DATASET_CONFIG["dataset"], "host": None}}

        with pytest.raises(ValueError, match="Incomplete dataset configuration"):
            make_pipe(**config)

    @pytest.mark.parametrize("schema, env_name", [("read_schema", "CDM_SCHEMA"), ("write_schema", "WRITE_SCHEMA")])
    def test_a_dataset_without_a_schema_is_accepted(self, pipes_env, schema, env_name):
        """A dataset's schemas are optional (Noneable in the op config and on the model)."""
        config = {"dataset": {**DATASET_CONFIG["dataset"], schema: None}}

        pipe = make_pipe(**config)

        assert pipe.dataset[schema] is None
        assert env_name not in pipe.env

    def test_dataset_schemas_are_exported_to_the_container(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)

        assert pipe.env["CDM_SCHEMA"] == "cdm_schema"
        assert pipe.env["WRITE_SCHEMA"] == "results"


class TestEnvironment:
    def test_artifact_path_is_per_run(self, pipes_env):
        pipe = make_pipe()

        assert pipe.artifact_path == "/mnt/dagster/artifacts/run-1"
        assert pipe.env["ARTIFACT_PATH"] == "/mnt/dagster/artifacts/run-1"

    def test_config_env_is_passed_through(self, pipes_env):
        pipe = make_pipe(env={"KEY": "value"})

        assert pipe.env["KEY"] == "value"

    def test_external_env_wins_over_config_env(self, pipes_env):
        pipe = make_pipe(env={"KEY": "config"}, ext_env={"KEY": "external"})

        assert pipe.env["KEY"] == "external"

    def test_pod_env_keys_are_upper_cased_strings(self, pipes_env):
        env = make_pipe(env={"lower": 1})._pod_env()

        assert {"name": "LOWER", "value": "1"} in env

    def test_no_connection_string_without_a_dataset(self, pipes_env):
        names = [e["name"] for e in make_pipe()._pod_env()]

        assert "CONNECTION_STRING" not in names

    def test_credentials_come_from_the_task_secret_not_the_pod_spec(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)

        with patch.object(pipes.SecretProvider, "get") as secret:
            env = pipe._pod_env()

        secret.assert_not_called()
        names = [e["name"] for e in env]
        assert env[names.index("DB_USERNAME")] == {
            "name": "DB_USERNAME", "valueFrom": {"secretKeyRef": {"name": "task-7", "key": "USERNAME"}}
        }
        assert env[names.index("DB_PASSWORD")] == {
            "name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "task-7", "key": "PASSWORD"}}
        }

    def test_connection_string_refers_to_the_secret_variables_defined_before_it(self, pipes_env):
        env = make_pipe(**DATASET_CONFIG)._pod_env()

        names = [e["name"] for e in env]
        connstr = env[names.index("CONNECTION_STRING")]["value"]
        assert connstr == (
            "driver={PostgreSQL ANSI};Uid=$(DB_USERNAME);Pwd=$(DB_PASSWORD);Server=db.host,5432;Database=cdm;"
        )
        assert names.index("DB_USERNAME") < names.index("CONNECTION_STRING")
        assert names.index("DB_PASSWORD") < names.index("CONNECTION_STRING")

    def test_the_credentials_are_read_from_the_dataset_secret(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)

        with patch.object(pipes.SecretProvider, "get", side_effect=["user", "pass"]) as secret:
            creds = pipe._get_dataset_creds()

        assert creds == {"USERNAME": "user", "PASSWORD": "pass"}
        assert secret.call_args_list[0].args == ("db-host-cdm-creds", "fn", "USERNAME")
        assert secret.call_args_list[1].args == ("db-host-cdm-creds", "fn", "PASSWORD")

    @pytest.mark.parametrize("db_type, expected", [
        ("mssql", "driver={ODBC Driver 18 for SQL Server};Uid=u;Pwd=p;Server=db.host,5432;Database=cdm;"),
        ("mysql", "driver={MySQL ODBC 9.3 ANSI Driver};Uid=u;Pwd=p;Server=db.host,5432;Database=cdm;"),
        ("mariadb", "driver={MariaDB ODBC 3.2 Driver};Uid=u;Pwd=p;Server=db.host,5432;Database=cdm;"),
        ("oracle", "driver={Oracle ODBC Driver};Uid=u;PSW=p;DBQ=db.host:5432/cdm;"),
    ])
    def test_connection_string_names_the_driver_for_the_dataset_type(self, pipes_env, db_type, expected):
        pipe = make_pipe(dataset={**DATASET_CONFIG["dataset"], "type": db_type})

        assert pipe._get_conn_str("u", "p") == expected


class TestArtifactDir:
    def _pipe_on(self, tmp_path, pipes_env):
        pipe = make_pipe()
        pipe.mnt_base_path = str(tmp_path)
        pipe.artifact_path = str(tmp_path / "run-1")
        return pipe

    def test_creates_the_run_directory(self, pipes_env, tmp_path):
        pipe = self._pipe_on(tmp_path, pipes_env)

        pipe._prepare_artifact_dir()

        assert os.path.isdir(pipe.artifact_path)

    def test_is_idempotent(self, pipes_env, tmp_path):
        pipe = self._pipe_on(tmp_path, pipes_env)

        pipe._prepare_artifact_dir()
        pipe._prepare_artifact_dir()

        assert os.path.isdir(pipe.artifact_path)

    def test_run_directory_is_world_writable(self, pipes_env, tmp_path):
        pipe = self._pipe_on(tmp_path, pipes_env)

        pipe._prepare_artifact_dir()

        assert os.stat(pipe.artifact_path).st_mode & 0o777 == 0o777
        assert os.stat(pipe.mnt_base_path).st_mode & 0o755 == 0o755

    def test_unwritable_mount_root_raises(self, pipes_env, tmp_path):
        """The task pod only mounts this folder, and the kubelet would create a missing one root-owned."""
        pipe = self._pipe_on(tmp_path, pipes_env)

        with patch("app.definitions.pipes.Path.mkdir", side_effect=OSError("read-only")):
            with pytest.raises(RuntimeError, match="read-only"):
                pipe._prepare_artifact_dir()

    def test_chmod_failure_is_tolerated(self, pipes_env, tmp_path):
        """CIFS rejects chmod outright and already mounts 0777."""
        pipe = self._pipe_on(tmp_path, pipes_env)

        with patch("app.definitions.pipes.os.chmod", side_effect=OSError("not supported")):
            pipe._prepare_artifact_dir()

        assert os.path.isdir(pipe.artifact_path)
        pipe.context.log.warning.assert_not_called()


class TestCall:
    def test_launches_the_pod_and_returns_the_artifact_path(self, pipes_env, tmp_path):
        client = MagicMock()
        pipe = make_pipe(client=client)
        pipe.mnt_base_path = str(tmp_path)
        pipe.artifact_path = str(tmp_path / "run-1")

        response = pipe()

        kwargs = client.run.call_args.kwargs
        assert kwargs["namespace"] == "tasks"
        assert kwargs["image"] == "ghcr.io/org/experiment:latest"
        assert kwargs["pod_wait_timeout"] == 21600 + TERMINATION_GRACE_PERIOD_SECONDS
        assert kwargs["base_pod_spec"]["restartPolicy"] == "Never"
        assert response.output.value == {"artifacts_path": pipe.artifact_path}

    def test_artifact_dir_exists_before_the_pod_starts(self, pipes_env, tmp_path):
        """A non-root analytical image cannot create it itself on most backends."""
        client = MagicMock()
        pipe = make_pipe(client=client)
        pipe.mnt_base_path = str(tmp_path)
        pipe.artifact_path = str(tmp_path / "run-1")
        seen = {}
        client.run.side_effect = lambda **_: seen.update(
            existed=os.path.isdir(pipe.artifact_path)
        )

        pipe()

        assert seen["existed"] is True


class TestTaskSecret:
    def _pipe_on(self, tmp_path, client, **config):
        pipe = make_pipe(client=client, **config)
        pipe.mnt_base_path = str(tmp_path)
        pipe.artifact_path = str(tmp_path / "run-1")
        return pipe

    def test_no_secret_without_a_dataset(self, pipes_env, tmp_path):
        pipe = self._pipe_on(tmp_path, MagicMock())

        with patch.object(pipes, "TaskSecret") as task_secret:
            pipe()

        task_secret.assert_not_called()

    def test_the_secret_holds_the_credentials_in_the_tasks_namespace_while_the_pod_runs(self, pipes_env, tmp_path):
        client = MagicMock()
        pipe = self._pipe_on(tmp_path, client, **DATASET_CONFIG)
        seen = {}
        client.run.side_effect = lambda **_: seen.update(entered=task_secret.return_value.__enter__.called)

        with patch.object(pipes.SecretProvider, "get", side_effect=["user", "pass"]), \
                patch.object(pipes, "TaskSecret") as task_secret:
            pipe()

        task_secret.assert_called_once_with("task-7", "tasks", {"USERNAME": "user", "PASSWORD": "pass"})
        assert seen["entered"] is True
        task_secret.return_value.__exit__.assert_called_once()

    def test_the_secret_is_deleted_when_the_task_fails(self, pipes_env, tmp_path):
        client = MagicMock()
        client.run.side_effect = RuntimeError("pod failed")
        pipe = self._pipe_on(tmp_path, client, **DATASET_CONFIG)

        with patch.object(pipes.SecretProvider, "get", side_effect=["user", "pass"]), \
                patch.object(pipes, "TaskSecret") as task_secret:
            with pytest.raises(RuntimeError, match="pod failed"):
                pipe()

        task_secret.return_value.__exit__.assert_called_once()

    def test_a_run_without_a_task_id_is_rejected(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)
        pipe.context.run.tags = {}

        with pytest.raises(KeyError, match="task_id"):
            pipe.task_secret_name


class TestResponse:
    def test_output_metadata(self):
        response = K8sPipesResponse(
            run_id="run-1",
            image="ghcr.io/org/experiment:latest",
            artifact_path="/mnt/artifacts/run-1",
            result=MagicMock(),
        )

        metadata = {k: v.value for k, v in response.output.metadata.items()}
        assert metadata == {
            "run_id": "run-1",
            "image": "ghcr.io/org/experiment:latest",
            "artifacts_path": "/mnt/artifacts/run-1",
        }


class TestSecretHelpers:
    def test_dict_to_pod_env(self):
        assert _dict_to_pod_env({"a": 1, "B": "two"}) == [
            {"name": "A", "value": "1"},
            {"name": "B", "value": "two"},
        ]
