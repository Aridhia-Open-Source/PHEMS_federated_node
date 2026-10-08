import base64
from unittest.mock import MagicMock, patch

import pytest

from app.models import SecretProviderType
from app.secrets import K8sSecretProvider, SecretProvider


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
