from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The operator's settings, from the environment the chart gives its Deployment"""

    model_config = SettingsConfigDict(case_sensitive=True, populate_by_name=True)

    nexus_api_url: str = Field(alias="NEXUS_API_URL")
    user: str = Field(alias="OPERATOR_KC_USER")
    # The mounted operator-keycloak-creds key, read at every login so a credential rotation needs no restart
    password_file: str = Field(alias="OPERATOR_KC_PASSWORD_FILE")
    # How often every resource is synced again: puts back UI edits and sees a rotated source Secret
    sync_interval_seconds: float = Field(default=60, alias="OPERATOR_SYNC_INTERVAL_SECONDS")
    # How long a resource waits before a retry: a missing dependency, a refused delete, an API error
    retry_delay_seconds: float = Field(default=60, alias="OPERATOR_RETRY_DELAY_SECONDS")
