from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, populate_by_name=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_required(cls, value):
        if not value:
            raise ValueError("required")
        return value
