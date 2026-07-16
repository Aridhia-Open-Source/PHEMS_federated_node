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
