import dagster as dg
import pytest

from app.backend import BackendAPI
from app.config import BackendConfig, GithubConfig, SensorConfig
from app.definitions.resources import (
    RESOURCES,
    backend_api,
    backend_config,
    github_api,
    github_config,
    sensor_config,
)
from app.github import GithubAPI


@pytest.fixture
def backend_env(monkeypatch):
    monkeypatch.setenv("BACKEND_API_URI", "http://backend.fn.svc:5000")
    monkeypatch.setenv("DAGSTER_KC_USER", "dagster")
    monkeypatch.setenv("DAGSTER_KC_PASSWORD", "secret")


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    monkeypatch.delenv("GH_API_URI", raising=False)


class TestConfigResources:
    def test_backend_config(self, backend_env):
        config = backend_config()

        assert isinstance(config, BackendConfig)
        assert config.uri == "http://backend.fn.svc:5000"

    def test_github_config(self, github_env):
        config = github_config()

        assert isinstance(config, GithubConfig)
        assert config.token == "gh-token"

    def test_sensor_config(self, monkeypatch, github_env):
        monkeypatch.setenv("DAGSTER_ARTIFACT_MOUNT_PATH", "/mnt/dagster/artifacts")
        monkeypatch.setenv("GH_RESULTS_DIR", "results")

        config = sensor_config()

        assert isinstance(config, SensorConfig)
        assert config.artifact_mount_path == "/mnt/dagster/artifacts"


class TestApiResources:
    def test_backend_api_is_built_from_its_config(self, backend_env):
        context = dg.build_init_resource_context(
            resources={"backend_config": BackendConfig()}
        )

        api = backend_api(context)

        assert isinstance(api, BackendAPI)
        assert api.session.base_url == "http://backend.fn.svc:5000"
        assert api.session.adapter.username == "dagster"

    def test_github_api_is_built_from_its_config(self, github_env):
        context = dg.build_init_resource_context(
            resources={"github_config": GithubConfig()}
        )

        api = github_api(context)

        assert isinstance(api, GithubAPI)
        assert api.client._base_uri == "https://api.github.com"

    def test_a_github_enterprise_host_is_honoured(self, github_env, monkeypatch):
        monkeypatch.setenv("GH_API_URI", "https://github.example.com/api/v3")
        context = dg.build_init_resource_context(
            resources={"github_config": GithubConfig()}
        )

        api = github_api(context)

        assert api.client._base_uri == "https://github.example.com/api/v3"


class TestRegistry:
    def test_every_resource_is_exported(self):
        assert set(RESOURCES) == {
            "backend_config", "sensor_config", "github_config",
            "backend_api", "github_api",
        }
