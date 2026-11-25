from unittest.mock import Mock, patch

from fednode.clients.kubernetes.client import KubernetesClient, load_kubernetes_config
from fednode.clients.kubernetes.mounted import MountedSecret


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
