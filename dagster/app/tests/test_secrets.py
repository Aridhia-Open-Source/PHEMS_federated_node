import base64
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from app.models import Secret, SecretProviderType
from app.secrets import K8sSecretProvider, SecretProvider, TaskSecret, read_secret_value
from app.tests.conftest import SAMPLE_SECRET


def encoded(value):
    return base64.b64encode(value.encode()).decode()


@pytest.fixture
def core_api():
    with patch("app.secrets.load_incluster_config"), patch("app.secrets.client.CoreV1Api") as api:
        yield api.return_value


class TestK8sSecretProvider:
    def test_the_value_is_base64_decoded(self, core_api):
        core_api.read_namespaced_secret.return_value = MagicMock(data={"TOKEN": encoded("s3cret")})

        assert K8sSecretProvider().get("git-token", "fn", "TOKEN") == "s3cret"
        core_api.read_namespaced_secret.assert_called_once_with("git-token", "fn")

    def test_a_secret_without_data_raises(self, core_api):
        core_api.read_namespaced_secret.return_value = MagicMock(data=None)

        with pytest.raises(ValueError, match="has no data"):
            K8sSecretProvider().get("git-token", "fn", "TOKEN")

    def test_a_missing_value_key_raises(self, core_api):
        core_api.read_namespaced_secret.return_value = MagicMock(data={"OTHER": encoded("x")})

        with pytest.raises(KeyError):
            K8sSecretProvider().get("git-token", "fn", "TOKEN")

    def test_a_missing_secret_raises(self, core_api):
        core_api.read_namespaced_secret.side_effect = RuntimeError("404")

        with pytest.raises(RuntimeError):
            K8sSecretProvider().get("nope", "fn", "TOKEN")


class TestTaskSecret:
    def test_creates_the_secret_on_entering_and_deletes_it_on_leaving(self, core_api):
        with TaskSecret("task-7", "tasks", {"USERNAME": "u", "PASSWORD": "p"}) as secret:
            assert secret.name == "task-7"
            body = core_api.create_namespaced_secret.call_args.args[1]
            assert core_api.create_namespaced_secret.call_args.args[0] == "tasks"
            assert body.metadata.name == "task-7"
            assert body.string_data == {"USERNAME": "u", "PASSWORD": "p"}
            core_api.delete_namespaced_secret.assert_not_called()

        core_api.delete_namespaced_secret.assert_called_once_with("task-7", "tasks")

    def test_deletes_the_secret_when_the_block_fails(self, core_api):
        with pytest.raises(RuntimeError):
            with TaskSecret("task-7", "tasks", {"PASSWORD": "p"}):
                raise RuntimeError("pod failed")

        core_api.delete_namespaced_secret.assert_called_once_with("task-7", "tasks")

    def test_replaces_a_secret_a_dead_run_left_behind(self, core_api):
        core_api.create_namespaced_secret.side_effect = [ApiException(status=409), None]

        with TaskSecret("task-7", "tasks", {"PASSWORD": "p"}):
            assert core_api.create_namespaced_secret.call_count == 2
            core_api.delete_namespaced_secret.assert_called_once_with("task-7", "tasks")

        assert core_api.delete_namespaced_secret.call_count == 2

    def test_any_other_create_failure_is_raised_and_nothing_is_deleted(self, core_api):
        core_api.create_namespaced_secret.side_effect = ApiException(status=403)

        with pytest.raises(ApiException):
            with TaskSecret("task-7", "tasks", {"PASSWORD": "p"}):
                pass

        core_api.delete_namespaced_secret.assert_not_called()


class TestSecretProvider:
    def test_k8s_selects_the_kubernetes_provider(self):
        assert isinstance(SecretProvider(SecretProviderType.K8S).provider, K8sSecretProvider)

    def test_get_delegates_to_the_provider(self):
        with patch.object(K8sSecretProvider, "get", return_value="v") as get:
            value = SecretProvider(SecretProviderType.K8S).get("key", "ns", "TOKEN")

        assert value == "v"
        get.assert_called_once_with("key", "ns", "TOKEN")

    def test_an_unknown_provider_raises(self):
        with pytest.raises(KeyError):
            SecretProvider("VAULT")


class TestReadSecretValue:
    def test_the_secret_is_read_from_the_namespace_of_its_row(self, core_api):
        core_api.read_namespaced_secret.return_value = MagicMock(data={"TOKEN": encoded("s3cret")})
        secret = Secret(**{**SAMPLE_SECRET, "namespace": "other-ns"})

        assert read_secret_value(secret, "TOKEN") == "s3cret"
        core_api.read_namespaced_secret.assert_called_once_with("git-token-abc", "other-ns")

    def test_a_disabled_secret_is_never_read(self, core_api):
        secret = Secret(**{**SAMPLE_SECRET, "enabled": False})

        with pytest.raises(PermissionError):
            read_secret_value(secret, "TOKEN")
        core_api.read_namespaced_secret.assert_not_called()
