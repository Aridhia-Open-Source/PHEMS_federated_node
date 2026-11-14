from kubernetes import client


def test_configuration_keeps_no_proxy_behind_a_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,.svc,10.96.0.1")
    configuration = client.Configuration()
    assert configuration.proxy == "http://proxy.example:3128"
    assert configuration.no_proxy == "localhost,.svc,10.96.0.1"
