"""Environment settings shared by federated node services.

Shared fields are optional; each service supplies its own required fields and
defaults by subclassing these models.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvSettings(BaseSettings):
    """Base for settings groups read directly from the container environment."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")


class NodeSettings(EnvSettings):
    """Node identity."""
    model_config = SettingsConfigDict(env_prefix="NODE_")

    id: str | None = None
    hostname: str | None = None


class NamespacesSettings(EnvSettings):
    """Kubernetes namespaces."""
    model_config = SettingsConfigDict(env_prefix="NAMESPACES_")

    deployment: str | None = None
    tasks: str | None = None
    secrets: str | None = None
    quarantine: str | None = None


class HttpSettings(EnvSettings):
    """Outbound HTTP timeouts."""
    model_config = SettingsConfigDict(env_prefix="HTTP_")

    connect_timeout: float | None = None
    read_timeout: float | None = None


class DatabaseSettings(EnvSettings):
    """Owned database connection."""
    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    host: str | None = None
    port: str | None = None
    name: str | None = None
    user: str | None = None
    password: str | None = None
    ssl: str | None = None


class NexusSettings(EnvSettings):
    """Nexus service connection."""
    model_config = SettingsConfigDict(env_prefix="SERVICES_NEXUS_")

    uri: str | None = None
    user: str | None = None
    password_file: str | None = None


class DagsterSettings(EnvSettings):
    """Dagster service connection."""
    model_config = SettingsConfigDict(env_prefix="SERVICES_DAGSTER_")

    uri: str | None = None


class KeycloakSettings(EnvSettings):
    """Keycloak service connection."""
    model_config = SettingsConfigDict(env_prefix="SERVICES_KEYCLOAK_")

    url: str | None = None
    realm: str | None = None
    client: str | None = None
    allowed_clients: str | None = None
    admin: str | None = None
    service_user: str | None = None
    secrets_path: str | None = None
    secret: str | None = None
    service_password: str | None = None
    token_cache_ttl: int | None = None
    login_attempts: int | None = None
    login_backoff: float | None = None
