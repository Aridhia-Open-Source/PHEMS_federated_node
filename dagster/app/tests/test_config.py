import pytest
from pydantic import ValidationError

from app.config import (
    BackendConfig,
    GithubConfig,
    GithubTransferConfig,
    PipesSecurityContextConfig,
    SensorConfig,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "BACKEND_API_URI", "DAGSTER_KC_USER", "DAGSTER_KC_PASSWORD",
        "DAGSTER_ARTIFACT_MOUNT_PATH", "GH_RESULTS_DIR", "GH_TOKEN",
        "GH_API_URI", "GH_DELIVERY_REPO", "GH_DELIVERY_BASE_BRANCH",
        "DAGSTER_PIPES_FS_GROUP", "DAGSTER_PIPES_RUN_AS_USER",
        "DAGSTER_PIPES_RUN_AS_GROUP", "DAGSTER_PIPES_SUPPLEMENTAL_GROUPS",
    ):
        monkeypatch.delenv(key, raising=False)


class TestEnvConfig:
    def test_values_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("BACKEND_API_URI", "http://backend.fn.svc:5000")
        monkeypatch.setenv("DAGSTER_KC_USER", "dagster")
        monkeypatch.setenv("DAGSTER_KC_PASSWORD", "secret")

        config = BackendConfig()

        assert config.uri == "http://backend.fn.svc:5000"
        assert config.user == "dagster"

    def test_a_missing_value_fails_loudly(self):
        with pytest.raises(ValidationError):
            BackendConfig()

    def test_an_empty_value_is_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv("BACKEND_API_URI", "")
        monkeypatch.setenv("DAGSTER_KC_USER", "dagster")
        monkeypatch.setenv("DAGSTER_KC_PASSWORD", "secret")

        with pytest.raises(ValidationError):
            BackendConfig()

    def test_github_api_uri_has_a_default(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "abc")

        assert GithubConfig().base_uri == "https://api.github.com"

    def test_transfer_config_defaults_to_the_main_branch(self, monkeypatch):
        for key in ("GH_TOKEN", "GH_DELIVERY_REPO", "GH_RESULTS_DIR",
                    "DAGSTER_ARTIFACT_MOUNT_PATH"):
            monkeypatch.setenv(key, "x")

        assert GithubTransferConfig().base_branch == "main"

    def test_sensor_config_requires_its_paths(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "abc")
        monkeypatch.setenv("GH_RESULTS_DIR", "results")

        with pytest.raises(ValidationError):
            SensorConfig()


class TestPipesSecurityContext:
    def test_unset_is_empty(self):
        assert PipesSecurityContextConfig().to_pod_security_context() == {}

    def test_all_fields(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_PIPES_FS_GROUP", "2001")
        monkeypatch.setenv("DAGSTER_PIPES_RUN_AS_USER", "1001")
        monkeypatch.setenv("DAGSTER_PIPES_RUN_AS_GROUP", "1002")
        monkeypatch.setenv("DAGSTER_PIPES_SUPPLEMENTAL_GROUPS", "1,2")

        assert PipesSecurityContextConfig().to_pod_security_context() == {
            "fsGroup": 2001,
            "runAsUser": 1001,
            "runAsGroup": 1002,
            "supplementalGroups": [1, 2],
        }

    def test_a_zero_uid_is_kept(self, monkeypatch):
        """runAsUser: 0 is meaningful - it is not the same as unset."""
        monkeypatch.setenv("DAGSTER_PIPES_RUN_AS_USER", "0")

        assert PipesSecurityContextConfig().to_pod_security_context() == {"runAsUser": 0}

    def test_blank_supplemental_groups_are_dropped(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_PIPES_SUPPLEMENTAL_GROUPS", "1, ,2")

        ctx = PipesSecurityContextConfig().to_pod_security_context()

        assert ctx["supplementalGroups"] == [1, 2]

    def test_an_empty_supplemental_group_list_is_omitted(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_PIPES_SUPPLEMENTAL_GROUPS", "")

        assert "supplementalGroups" not in PipesSecurityContextConfig().to_pod_security_context()
