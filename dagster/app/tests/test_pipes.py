import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from app.definitions import pipes
from app.definitions.pipes import (
    K8sPipe,
    K8sPipesResponse,
    TERMINATION_GRACE_PERIOD_SECONDS,
    _dict_to_pod_env,
    _get_k8s_secret,
)


PIPES_ENV = {
    "DAGSTER_DEPLOYMENT_NAMESPACE": "fn",
    "DAGSTER_TASK_NAMESPACE": "tasks",
    "DAGSTER_ARTIFACTS_PVC_NAME": "artifacts-pvc",
    "DAGSTER_ARTIFACT_MOUNT_PATH": "/mnt/dagster/artifacts",
}

SECURITY_CONTEXT_ENV = (
    "DAGSTER_PIPES_FS_GROUP",
    "DAGSTER_PIPES_RUN_AS_USER",
    "DAGSTER_PIPES_RUN_AS_GROUP",
    "DAGSTER_PIPES_SUPPLEMENTAL_GROUPS",
)

DATASET_CONFIG = {
    "dataset_secret_name": "db-host-cdm-creds",
    "dataset_name": "cdm",
    "dataset_host": "db.host",
    "dataset_port": 5432,
    "dataset_type": "postgres",
    "dataset_schema": "cdm_schema",
    "dataset_schema_write": "results",
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

    def test_volume_is_the_artifacts_claim(self, pipes_env):
        spec = make_pipe()._build_base_pod_spec()

        assert spec["volumes"] == [{
            "name": "artifacts-pvc",
            "persistentVolumeClaim": {"claimName": "artifacts-pvc"},
        }]
        assert spec["containers"][0]["volumeMounts"] == [{
            "name": "artifacts-pvc",
            "mountPath": "/mnt/dagster/artifacts",
        }]

    def test_container_is_named_for_the_run(self, pipes_env):
        spec = make_pipe()._build_base_pod_spec()

        assert spec["containers"][0]["name"] == "pipes-run-1"


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

    def test_dataset_fields_are_unprefixed(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)

        assert pipe.dataset == {
            "secret_name": "db-host-cdm-creds",
            "name": "cdm",
            "host": "db.host",
            "port": 5432,
            "type": "postgres",
            "schema": "cdm_schema",
            "schema_write": "results",
        }

    def test_incomplete_dataset_is_rejected(self, pipes_env):
        config = dict(DATASET_CONFIG)
        config.pop("dataset_host")

        with pytest.raises(ValueError, match="Incomplete dataset configuration"):
            make_pipe(**config)

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

    def test_connection_string_is_resolved_from_the_secret(self, pipes_env):
        pipe = make_pipe(**DATASET_CONFIG)

        with patch.object(pipes, "_get_k8s_secret", side_effect=["user", "pass"]) as secret:
            env = pipe._pod_env()

        connstr = next(e["value"] for e in env if e["name"] == "CONNECTION_STRING")
        assert connstr == (
            "server=db.host;database=cdm;port=5432;uid=user;pwd=pass;"
        )
        assert secret.call_args_list[0].args == ("db-host-cdm-creds", "fn", "USERNAME")
        assert secret.call_args_list[1].args == ("db-host-cdm-creds", "fn", "PASSWORD")

    def test_dataset_secret_is_read_from_the_deployment_namespace(self, pipes_env):
        """The task namespace holds no dataset credentials - the run pod reads its own."""
        pipe = make_pipe(**DATASET_CONFIG)

        with patch.object(pipes, "_get_k8s_secret", return_value="x") as secret:
            pipe._pod_env()

        assert all(call.args[1] == "fn" for call in secret.call_args_list)


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

    def test_unwritable_mount_root_warns_rather_than_raising(self, pipes_env, tmp_path):
        pipe = self._pipe_on(tmp_path, pipes_env)

        with patch("app.definitions.pipes.Path.mkdir", side_effect=OSError("read-only")):
            pipe._prepare_artifact_dir()

        pipe.context.log.warning.assert_called_once()
        assert "read-only" in pipe.context.log.warning.call_args.args[0]

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

    @patch("app.definitions.pipes.load_incluster_config")
    @patch("app.definitions.pipes.client.CoreV1Api")
    def test_secret_value_is_base64_decoded(self, core_api, _config):
        secret = MagicMock()
        secret.data = {"USERNAME": base64.b64encode(b"admin").decode()}
        core_api.return_value.read_namespaced_secret.return_value = secret

        assert _get_k8s_secret("creds", "fn", "USERNAME") == "admin"
        core_api.return_value.read_namespaced_secret.assert_called_once_with("creds", "fn")

    @patch("app.definitions.pipes.load_incluster_config")
    @patch("app.definitions.pipes.client.CoreV1Api")
    def test_empty_secret_raises(self, core_api, _config):
        secret = MagicMock()
        secret.data = None
        core_api.return_value.read_namespaced_secret.return_value = secret

        with pytest.raises(ValueError, match="has no data"):
            _get_k8s_secret("creds", "fn", "USERNAME")
