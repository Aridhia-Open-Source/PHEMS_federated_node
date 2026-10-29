import dagster as dg
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        populate_by_name=True,
    )

    @field_validator("*", mode="after")
    @classmethod
    def validate_required(cls, v: str) -> str:
        if not v:
            raise ValueError("required")
        return v


class BackendConfig(EnvConfig):
    uri: str = Field(default="", alias="NEXUS_API_URL")
    user: str = Field(default="", alias="DAGSTER_KC_USER")
    password: str = Field(default="", alias="DAGSTER_KC_PASSWORD")


class SensorStatusConfig(EnvConfig):
    initial_status: dg.DefaultSensorStatus = Field(
        default=dg.DefaultSensorStatus.STOPPED, alias="DAGSTER_SENSORS_INITIAL_STATUS"
    )
    min_interval_seconds: int = Field(default=30, alias="DAGSTER_SENSORS_MIN_INTERVAL_SECONDS")
    retry_interval_seconds: int = Field(default=60, alias="DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS")
    delivery_max_attempts: int = Field(default=5, alias="DAGSTER_DELIVERY_MAX_ATTEMPTS")


# Read once, at import: every sensor's default_status and minimum_interval_seconds.
DEFAULT_SENSOR_STATUS = SensorStatusConfig().initial_status
MIN_SENSOR_INTERVAL_SECONDS = SensorStatusConfig().min_interval_seconds
SENSOR_RETRY_INTERVAL_SECONDS = SensorStatusConfig().retry_interval_seconds
DELIVERY_MAX_ATTEMPTS = SensorStatusConfig().delivery_max_attempts


class ResultsDeliveryConfig(EnvConfig):
    artifact_mount_path: str = Field(default="", alias="DAGSTER_ARTIFACT_MOUNT_PATH")
    max_zip_bytes: int = Field(default=10485760, alias="RESULTS_MAX_ZIP_BYTES")


class ArtifactsVolumeConfig(EnvConfig):
    """The artifacts volume as the chart sets it for every pod that mounts it: its claim and where it is mounted."""

    pvc_name: str = Field(default="", alias="DAGSTER_ARTIFACTS_PVC_NAME")
    mount_path: str = Field(default="", alias="DAGSTER_ARTIFACT_MOUNT_PATH")


class PipesSecurityContextConfig(BaseSettings):
    """
    Optional pod securityContext for pipes task pods.

    Not an EnvConfig subclass on purpose: EnvConfig.validate_required rejects any
    falsy value, and every field here is legitimately unset by default.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        populate_by_name=True,
    )

    fs_group: int | None = Field(default=None, alias="DAGSTER_PIPES_FS_GROUP")
    run_as_user: int | None = Field(default=None, alias="DAGSTER_PIPES_RUN_AS_USER")
    run_as_group: int | None = Field(default=None, alias="DAGSTER_PIPES_RUN_AS_GROUP")
    supplemental_groups: str = Field(
        default="", alias="DAGSTER_PIPES_SUPPLEMENTAL_GROUPS"
    )

    def to_pod_security_context(self) -> dict:
        """
        Only the keys that are actually set. An unset runAsUser has to be absent
        rather than null, which the Kubernetes API rejects.
        """
        ctx = {}
        if self.fs_group is not None:
            ctx["fsGroup"] = self.fs_group
        if self.run_as_user is not None:
            ctx["runAsUser"] = self.run_as_user
        if self.run_as_group is not None:
            ctx["runAsGroup"] = self.run_as_group
        if self.supplemental_groups:
            ctx["supplementalGroups"] = [
                int(g) for g in self.supplemental_groups.split(",")  # pylint: disable=no-member  # pydantic FieldInfo
                if g.strip()
            ]
        return ctx

    def to_container_security_context(self) -> dict:
        """What every task container is held to, whatever the pod's identity: no privilege escalation, no
        capabilities, the runtime's seccomp profile and a non-root uid. Needs an image with a USER or a runAsUser."""
        return {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
            "runAsNonRoot": True,
        }
