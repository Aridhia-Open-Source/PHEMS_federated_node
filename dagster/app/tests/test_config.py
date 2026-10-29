import dagster as dg
import pytest
from pydantic import ValidationError

from app.config import (
    ArtifactsVolumeConfig,
    BackendConfig,
    PipesSecurityContextConfig,
    ResultsDeliveryConfig,
    SensorStatusConfig,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "NEXUS_API_URL", "DAGSTER_KC_USER", "DAGSTER_KC_PASSWORD",
        "DAGSTER_ARTIFACT_MOUNT_PATH", "DAGSTER_ARTIFACTS_PVC_NAME", "GH_RESULTS_DIR", "GH_TOKEN",
        "GH_API_URI", "GH_DELIVERY_REPO", "GH_DELIVERY_BASE_BRANCH",
        "DAGSTER_PIPES_FS_GROUP", "DAGSTER_PIPES_RUN_AS_USER",
        "DAGSTER_PIPES_RUN_AS_GROUP", "DAGSTER_PIPES_SUPPLEMENTAL_GROUPS",
        "DAGSTER_SENSORS_INITIAL_STATUS", "DAGSTER_SENSORS_MIN_INTERVAL_SECONDS",
        "DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS", "DAGSTER_DELIVERY_MAX_ATTEMPTS", "RESULTS_MAX_ZIP_BYTES",
    ):
        monkeypatch.delenv(key, raising=False)


class TestEnvConfig:
    def test_values_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("NEXUS_API_URL", "http://nexus-api.fn.svc:5000")
        monkeypatch.setenv("DAGSTER_KC_USER", "dagster")
        monkeypatch.setenv("DAGSTER_KC_PASSWORD", "secret")

        config = BackendConfig()

        assert config.uri == "http://nexus-api.fn.svc:5000"
        assert config.user == "dagster"

    def test_a_missing_value_fails_loudly(self):
        with pytest.raises(ValidationError):
            BackendConfig()

    def test_an_empty_value_is_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv("NEXUS_API_URL", "")
        monkeypatch.setenv("DAGSTER_KC_USER", "dagster")
        monkeypatch.setenv("DAGSTER_KC_PASSWORD", "secret")

        with pytest.raises(ValidationError):
            BackendConfig()


class TestSensorStatusConfig:
    def test_stopped_by_default(self):
        assert SensorStatusConfig().initial_status == dg.DefaultSensorStatus.STOPPED

    def test_running_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_SENSORS_INITIAL_STATUS", "RUNNING")

        assert SensorStatusConfig().initial_status == dg.DefaultSensorStatus.RUNNING

    def test_any_other_status_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_SENSORS_INITIAL_STATUS", "PAUSED")

        with pytest.raises(ValidationError):
            SensorStatusConfig()

    def test_min_interval_is_30_seconds_by_default(self):
        assert SensorStatusConfig().min_interval_seconds == 30

    def test_min_interval_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_SENSORS_MIN_INTERVAL_SECONDS", "2")

        assert SensorStatusConfig().min_interval_seconds == 2

    def test_retry_interval_is_60_seconds_by_default(self):
        assert SensorStatusConfig().retry_interval_seconds == 60

    def test_delivery_max_attempts_is_5_by_default_and_from_the_environment(self, monkeypatch):
        assert SensorStatusConfig().delivery_max_attempts == 5
        monkeypatch.setenv("DAGSTER_DELIVERY_MAX_ATTEMPTS", "2")

        assert SensorStatusConfig().delivery_max_attempts == 2

    def test_retry_interval_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS", "5")

        assert SensorStatusConfig().retry_interval_seconds == 5


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


    def test_the_container_is_locked_down_whatever_the_pod_identity(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_PIPES_RUN_AS_USER", "1001")

        assert PipesSecurityContextConfig().to_container_security_context() == {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
            "runAsNonRoot": True,
        }


class TestArtifactsVolumeConfig:
    def test_values_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_ARTIFACTS_PVC_NAME", "claim")
        monkeypatch.setenv("DAGSTER_ARTIFACT_MOUNT_PATH", "/artifacts")

        config = ArtifactsVolumeConfig()

        assert (config.pvc_name, config.mount_path) == ("claim", "/artifacts")

    def test_a_missing_value_is_rejected(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_ARTIFACT_MOUNT_PATH", "/artifacts")

        with pytest.raises(ValueError):
            ArtifactsVolumeConfig()


class TestResultsDeliveryConfig:
    def test_the_zip_cap_is_10_mib_by_default(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_ARTIFACT_MOUNT_PATH", "/artifacts")

        assert ResultsDeliveryConfig().max_zip_bytes == 10 * 1024 * 1024

    def test_the_zip_cap_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("DAGSTER_ARTIFACT_MOUNT_PATH", "/artifacts")
        monkeypatch.setenv("RESULTS_MAX_ZIP_BYTES", "2048")

        assert ResultsDeliveryConfig().max_zip_bytes == 2048
