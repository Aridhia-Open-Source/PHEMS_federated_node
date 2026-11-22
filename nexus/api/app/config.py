"""nexus-api settings read from the environment (pydantic-settings)."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.helpers.keycloak import KEYCLOAK_CLIENT, KEYCLOAK_URL, REALM


class AccessTokenConfig(BaseSettings):
    """
    How nexus-api checks Keycloak access tokens (ADR 0036). Tokens are issued for Keycloak's address on the node's
    host (KC_HOSTNAME); the keys are fetched in-cluster. The chart sets both.
    """
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, populate_by_name=True)

    issuer: str = Field(default=f"{KEYCLOAK_URL}/realms/{REALM}", alias="KEYCLOAK_ISSUER")
    jwks_url: str = Field(
        default=f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs", alias="KEYCLOAK_JWKS_URL"
    )
    client: str = Field(default=KEYCLOAK_CLIENT, alias="KEYCLOAK_CLIENT")
