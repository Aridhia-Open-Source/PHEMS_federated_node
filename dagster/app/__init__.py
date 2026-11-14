import os

from kubernetes import client

# kubernetes 35 reads NO_PROXY in Configuration() and then resets it to None, so with the chart's proxy
# value set every call to the API server goes to the proxy, which cannot reach it. Here rather than per
# call because dagster_k8s builds its own Configuration. Drop this with kubernetes 36 or later, which
# fixes it; dagster-k8s 0.28 still requires kubernetes<36.
_configuration_init = client.Configuration.__init__


def _configuration_init_with_no_proxy(self, *args, **kwargs):
    _configuration_init(self, *args, **kwargs)
    if self.no_proxy is None:
        self.no_proxy = os.getenv("no_proxy") or os.getenv("NO_PROXY")


client.Configuration.__init__ = _configuration_init_with_no_proxy
