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
    uri: str = Field(default="", alias="BACKEND_API_URI")
    user: str = Field(default="", alias="DAGSTER_KC_USER")
    password: str = Field(default="", alias="DAGSTER_KC_PASSWORD")


class SensorConfig(EnvConfig):
    artifact_mount_path: str = Field(default="", alias="DAGSTER_ARTIFACT_MOUNT_PATH")
    results_dir: str = Field(default="", alias="GH_RESULTS_DIR")
    token: str = Field(default="", alias="GH_TOKEN")


class GithubConfig(EnvConfig):
    token: str = Field(default="", alias="GH_TOKEN")
    base_uri: str = Field(
        default="https://api.github.com",
        alias="GH_API_URI",
    )


class GithubTransferConfig(EnvConfig):
    token: str = Field(default="", alias="GH_TOKEN")
    delivery_repo: str = Field(default="", alias="GH_DELIVERY_REPO")
    base_branch: str = Field(default="main", alias="GH_DELIVERY_BASE_BRANCH")
    results_dir: str = Field(default="", alias="GH_RESULTS_DIR")
    artifact_mount_path: str = Field(default="", alias="DAGSTER_ARTIFACT_MOUNT_PATH")


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
                int(g) for g in self.supplemental_groups.split(",") if g.strip()
            ]
        return ctx
