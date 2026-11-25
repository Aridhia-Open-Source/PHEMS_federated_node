import dagster as dg
import pytest
from pydantic import ValidationError

from app.settings.groups import (
    ArtifactsSettings,
    NexusSettings,
    NodeSettings,
    SecuritySettings,
    ResultsSettings,
    SensorsSettings,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "SERVICES_NEXUS_URI", "SERVICES_NEXUS_USER", "SERVICES_NEXUS_PASSWORD_FILE",
        "ARTIFACTS_MOUNT_PATH", "ARTIFACTS_PVC_NAME", "GH_RESULTS_DIR", "GH_TOKEN",
        "GH_API_URI", "GH_DELIVERY_REPO", "GH_DELIVERY_BASE_BRANCH",
        "TASKS_SECURITY_FS_GROUP", "TASKS_SECURITY_RUN_AS_USER",
        "TASKS_SECURITY_RUN_AS_GROUP", "TASKS_SECURITY_SUPPLEMENTAL_GROUPS",
        "SENSORS_INITIAL_STATUS", "SENSORS_MIN_INTERVAL_SECONDS",
        "SENSORS_RETRY_INTERVAL_SECONDS", "RESULTS_MAX_ATTEMPTS", "RESULTS_MAX_ZIP_BYTES", "NODE_ID",
    ):
        monkeypatch.delenv(key, raising=False)


class TestEnvConfig:
    def test_values_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("SERVICES_NEXUS_URI", "http://nexus-api.fn.svc:5000")
        monkeypatch.setenv("SERVICES_NEXUS_USER", "dagster")
        monkeypatch.setenv("SERVICES_NEXUS_PASSWORD_FILE", "/etc/secrets/dagster/DAGSTER_KC_PASSWORD")

        config = NexusSettings()

        assert config.uri == "http://nexus-api.fn.svc:5000"
        assert config.user == "dagster"

    def test_a_missing_value_fails_loudly(self):
        with pytest.raises(ValidationError):
            NexusSettings()

    def test_an_empty_value_is_treated_as_missing(self, monkeypatch):
        monkeypatch.setenv("SERVICES_NEXUS_URI", "")
        monkeypatch.setenv("SERVICES_NEXUS_USER", "dagster")
        monkeypatch.setenv("SERVICES_NEXUS_PASSWORD_FILE", "/etc/secrets/dagster/DAGSTER_KC_PASSWORD")

        with pytest.raises(ValidationError):
            NexusSettings()


class TestSensorsSettings:
    def test_stopped_by_default(self):
        assert SensorsSettings().initial_status == dg.DefaultSensorStatus.STOPPED

    def test_running_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("SENSORS_INITIAL_STATUS", "RUNNING")

        assert SensorsSettings().initial_status == dg.DefaultSensorStatus.RUNNING

    def test_any_other_status_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("SENSORS_INITIAL_STATUS", "PAUSED")

        with pytest.raises(ValidationError):
            SensorsSettings()

    def test_min_interval_is_30_seconds_by_default(self):
        assert SensorsSettings().min_interval_seconds == 30

    def test_min_interval_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("SENSORS_MIN_INTERVAL_SECONDS", "2")

        assert SensorsSettings().min_interval_seconds == 2

    def test_retry_interval_is_60_seconds_by_default(self):
        assert SensorsSettings().retry_interval_seconds == 60

    def test_delivery_max_attempts_is_5_by_default_and_from_the_environment(self, monkeypatch):
        assert ResultsSettings().max_attempts == 5
        monkeypatch.setenv("RESULTS_MAX_ATTEMPTS", "2")

        assert ResultsSettings().max_attempts == 2

    def test_retry_interval_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("SENSORS_RETRY_INTERVAL_SECONDS", "5")

        assert SensorsSettings().retry_interval_seconds == 5


class TestPipesSecurityContext:
    def test_unset_is_empty(self):
        assert SecuritySettings().to_pod_security_context() == {}

    def test_all_fields(self, monkeypatch):
        monkeypatch.setenv("TASKS_SECURITY_FS_GROUP", "2001")
        monkeypatch.setenv("TASKS_SECURITY_RUN_AS_USER", "1001")
        monkeypatch.setenv("TASKS_SECURITY_RUN_AS_GROUP", "1002")
        monkeypatch.setenv("TASKS_SECURITY_SUPPLEMENTAL_GROUPS", "1,2")

        assert SecuritySettings().to_pod_security_context() == {
            "fsGroup": 2001,
            "runAsUser": 1001,
            "runAsGroup": 1002,
            "supplementalGroups": [1, 2],
        }

    def test_a_zero_uid_is_kept(self, monkeypatch):
        """runAsUser: 0 is meaningful - it is not the same as unset."""
        monkeypatch.setenv("TASKS_SECURITY_RUN_AS_USER", "0")

        assert SecuritySettings().to_pod_security_context() == {"runAsUser": 0}

    def test_blank_supplemental_groups_are_dropped(self, monkeypatch):
        monkeypatch.setenv("TASKS_SECURITY_SUPPLEMENTAL_GROUPS", "1, ,2")

        ctx = SecuritySettings().to_pod_security_context()

        assert ctx["supplementalGroups"] == [1, 2]

    def test_an_empty_supplemental_group_list_is_omitted(self, monkeypatch):
        monkeypatch.setenv("TASKS_SECURITY_SUPPLEMENTAL_GROUPS", "")

        assert "supplementalGroups" not in SecuritySettings().to_pod_security_context()


    def test_the_container_is_locked_down_whatever_the_pod_identity(self, monkeypatch):
        monkeypatch.setenv("TASKS_SECURITY_RUN_AS_USER", "1001")

        assert SecuritySettings().to_container_security_context() == {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
            "runAsNonRoot": True,
        }


class TestArtifactsSettings:
    def test_values_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("ARTIFACTS_PVC_NAME", "claim")
        monkeypatch.setenv("ARTIFACTS_MOUNT_PATH", "/artifacts")

        config = ArtifactsSettings()

        assert (config.pvc_name, config.mount_path) == ("claim", "/artifacts")

    def test_a_missing_value_is_rejected(self, monkeypatch):
        monkeypatch.setenv("ARTIFACTS_MOUNT_PATH", "/artifacts")

        with pytest.raises(ValueError):
            ArtifactsSettings()


class TestResultsSettings:
    def test_the_zip_cap_is_10_mib_by_default(self, monkeypatch):
        monkeypatch.setenv("ARTIFACTS_MOUNT_PATH", "/artifacts")
        monkeypatch.setenv("NODE_ID", "node-1")

        assert ResultsSettings().max_zip_bytes == 10 * 1024 * 1024

    def test_the_zip_cap_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("ARTIFACTS_MOUNT_PATH", "/artifacts")
        monkeypatch.setenv("NODE_ID", "node-1")
        monkeypatch.setenv("RESULTS_MAX_ZIP_BYTES", "2048")

        assert ResultsSettings().max_zip_bytes == 2048

    def test_the_node_id_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("ARTIFACTS_MOUNT_PATH", "/artifacts")
        monkeypatch.setenv("NODE_ID", "node-1")

        assert NodeSettings().id == "node-1"

    @pytest.mark.parametrize("node_id", [None, ""])
    def test_a_missing_or_empty_node_id_is_rejected(self, monkeypatch, node_id):
        monkeypatch.setenv("ARTIFACTS_MOUNT_PATH", "/artifacts")
        if node_id is not None:
            monkeypatch.setenv("NODE_ID", node_id)

        with pytest.raises(ValidationError):
            NodeSettings()
