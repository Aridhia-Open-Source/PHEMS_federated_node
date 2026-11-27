import json
from unittest.mock import Mock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from fednode.clients.kubernetes.client import KubernetesClient, KubernetesError, load_kubernetes_config
from fednode.clients.kubernetes.mounted import MountedSecret
from fednode.clients.kubernetes.names import InvalidName, validate_dns_label
from fednode.http import ClientError


def test_in_cluster_config_preserves_no_proxy(monkeypatch):
    load_kubernetes_config.cache_clear()
    monkeypatch.setenv("NO_PROXY", "localhost,.svc")
    configuration = Mock()
    with patch("fednode.clients.kubernetes.client.config.load_incluster_config") as load, patch(
        "fednode.clients.kubernetes.client.client.Configuration.get_default_copy",
        return_value=configuration,
    ), patch("fednode.clients.kubernetes.client.client.Configuration.set_default") as set_default:
        load_kubernetes_config(in_cluster=True)

    load.assert_called_once_with()
    assert configuration.no_proxy == "localhost,.svc"
    set_default.assert_called_once_with(configuration)
    load_kubernetes_config.cache_clear()


def test_kubernetes_config_is_loaded_once_per_mode():
    load_kubernetes_config.cache_clear()
    with patch("fednode.clients.kubernetes.client.config.load_kube_config") as load:
        load_kubernetes_config(in_cluster=False)
        load_kubernetes_config(in_cluster=False)

    load.assert_called_once_with()
    load_kubernetes_config.cache_clear()


def test_mounted_secret_reads_a_fresh_value_each_time(monkeypatch):
    values = iter(["first\n", "second\n"])

    class OpenFile:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return next(values)

    with patch("fednode.clients.kubernetes.mounted.Path.open", return_value=OpenFile()) as open_file:
        mounted = MountedSecret("/secrets")
        assert mounted.read("TOKEN") == "first"
        assert mounted.read("TOKEN") == "second"

    assert open_file.call_count == 2
    monkeypatch.delenv("TOKEN", raising=False)


def test_mounted_secret_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("TOKEN", "from environment")
    with patch("fednode.clients.kubernetes.mounted.Path.open", side_effect=FileNotFoundError):
        assert MountedSecret("/secrets").read("TOKEN") == "from environment"


def test_secret_data_helpers_round_trip():
    encoded = KubernetesClient.encode_secret_value("secret-value")
    assert KubernetesClient.decode_secret_value(encoded) == "secret-value"


def test_a_kubernetes_error_carries_the_status_and_causes_of_a_json_body():
    error = KubernetesError(json.dumps({"code": 422, "details": {"causes": [{"field": "data"}]}}))

    assert isinstance(error, ClientError)
    assert (error.code, error.extra_fields) == (422, [{"field": "data"}])
    assert error.description == "An unexpected kubernetes error occurred. Check the details field"


def test_a_kubernetes_error_without_details_has_no_causes():
    error = KubernetesError(json.dumps({"code": 404, "reason": "NotFound", "message": "secrets \"x\" not found"}))

    assert (error.code, error.extra_fields) == (404, [])


def test_a_kubernetes_error_with_a_plain_body_is_a_500_with_that_message():
    error = KubernetesError("Forbidden")

    assert (error.code, error.description, error.extra_fields) == (500, "Forbidden", None)


def test_a_refused_secret_patch_is_a_kubernetes_error():
    with patch("fednode.clients.kubernetes.client.load_kubernetes_config"), patch.object(
        KubernetesClient, "patch_namespaced_secret", side_effect=ApiException(http_resp=Mock(status=403, data="Forbidden"))
    ):
        with pytest.raises(KubernetesError, match="Forbidden"):
            KubernetesClient(in_cluster=False).patch_secret_data("a-secret", "default", {"KEY": "value"})


def test_an_invalid_name_is_a_value_error():
    with pytest.raises(InvalidName, match="name must be") as raised:
        validate_dns_label("A", "name")

    assert isinstance(raised.value, ValueError)
