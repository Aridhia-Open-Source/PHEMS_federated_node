from unittest.mock import MagicMock

import dagster as dg
import pytest

from app.backend import BackendAPI
from app.config import BackendConfig
from app.definitions.resources import (
    RESOURCES,
    backend_api,
    backend_config,
    git_apis,
)
from app.definitions.sensors.git.base import GitAPIFactory


@pytest.fixture
def backend_env(monkeypatch):
    monkeypatch.setenv("NEXUS_API_URL", "http://nexus-api.fn.svc:5000")
    monkeypatch.setenv("DAGSTER_KC_USER", "dagster")
    monkeypatch.setenv("DAGSTER_KC_PASSWORD", "secret")


class TestConfigResources:
    def test_backend_config(self, backend_env):
        config = backend_config()

        assert isinstance(config, BackendConfig)
        assert config.uri == "http://nexus-api.fn.svc:5000"


class TestApiResources:
    def test_backend_api_is_built_from_its_config(self, backend_env):
        context = dg.build_init_resource_context(
            resources={"backend_config": BackendConfig()}
        )

        api = backend_api(context)

        assert isinstance(api, BackendAPI)
        assert api.session.base_url == "http://nexus-api.fn.svc:5000"
        assert api.session.adapter.username == "dagster"

    def test_git_apis_are_built_on_the_backend_api(self):
        backend = MagicMock()
        context = dg.build_init_resource_context(resources={"backend_api": backend})

        factory = git_apis(context)

        assert isinstance(factory, GitAPIFactory)
        assert factory.backend_api is backend


class TestRegistry:
    def test_every_resource_is_exported(self):
        assert set(RESOURCES) == {"backend_config", "backend_api", "git_apis"}
