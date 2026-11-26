"""Dagster's settings groups."""
import dagster as dg
from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from fednode import settings as shared

TERMINATION_GRACE_PERIOD_SECONDS = 300
RUN_LABEL = "fn/run_id"
TASK_LABEL = "fn/task_id"
CONFIG_FILE_NAME = "config.json"
CONFIG_FILE_PATH = f"/etc/task/{CONFIG_FILE_NAME}"
CONFIG_VOLUME_NAME = "task-config"


class NodeSettings(shared.NodeSettings):
    id: str

    @field_validator("id")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("required")
        return value


class NamespacesSettings(shared.NamespacesSettings):
    deployment: str
    tasks: str

    @field_validator("deployment", "tasks")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("required")
        return value


class HttpSettings(shared.HttpSettings):
    connect_timeout: float = 3
    read_timeout: float = 10


class NexusSettings(shared.NexusSettings):
    uri: str
    user: str
    password_file: str

    @field_validator("uri", "user", "password_file")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("required")
        return value


class ServicesSettings(shared.EnvSettings):
    nexus: NexusSettings = Field(default_factory=NexusSettings)


class ArtifactsSettings(shared.EnvSettings):
    model_config = SettingsConfigDict(env_prefix="ARTIFACTS_")

    pvc_name: str
    mount_path: str

    @field_validator("pvc_name", "mount_path")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("required")
        return value


class SecuritySettings(shared.EnvSettings):
    model_config = SettingsConfigDict(env_prefix="TASKS_SECURITY_")

    fs_group: int | None = None
    run_as_user: int | None = None
    run_as_group: int | None = None
    supplemental_groups: str = ""

    def to_pod_security_context(self) -> dict:
        ctx = {}
        if self.fs_group is not None:
            ctx["fsGroup"] = self.fs_group
        if self.run_as_user is not None:
            ctx["runAsUser"] = self.run_as_user
        if self.run_as_group is not None:
            ctx["runAsGroup"] = self.run_as_group
        if self.supplemental_groups:
            ctx["supplementalGroups"] = [int(g) for g in self.supplemental_groups.split(",") if g.strip()]
        return ctx

    def to_container_security_context(self) -> dict:
        return {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
            "runAsNonRoot": True,
        }


class TasksSettings(shared.EnvSettings):
    model_config = SettingsConfigDict(env_prefix="TASKS_")

    active_deadline_seconds: int
    security: SecuritySettings = Field(default_factory=SecuritySettings)


class ResultsSettings(shared.EnvSettings):
    model_config = SettingsConfigDict(env_prefix="RESULTS_")

    max_zip_bytes: int = 10485760
    max_attempts: int = 5


class SensorsSettings(shared.EnvSettings):
    model_config = SettingsConfigDict(env_prefix="SENSORS_")

    initial_status: dg.DefaultSensorStatus = dg.DefaultSensorStatus.STOPPED
    min_interval_seconds: int = 30
    retry_interval_seconds: int = 60
