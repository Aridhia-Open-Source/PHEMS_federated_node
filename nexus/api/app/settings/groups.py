"""Nexus API's settings groups."""
# pylint: disable=too-few-public-methods

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from fednode import settings as shared


class NodeSettings(shared.NodeSettings):
    """Public node identity."""
    hostname: str


class NamespacesSettings(shared.NamespacesSettings):
    """Namespaces used by the API."""
    tasks: str
    secrets: str
    quarantine: str = "fn-quarantine"


class HttpSettings(shared.HttpSettings):
    """Default outbound timeouts in seconds."""
    connect_timeout: float = 3
    read_timeout: float = 10


class DatabaseSettings(shared.DatabaseSettings):
    """API database connection."""
    host: str
    port: str
    name: str
    user: str
    password: str
    ssl: str = ""


class DagsterSettings(shared.DagsterSettings):
    """Dagster webserver endpoint."""
    uri: str


class KeycloakSettings(shared.KeycloakSettings):
    """Keycloak endpoint and credential settings."""
    url: str
    realm: str = "FederatedNode"
    client: str = "global"
    service_user: str = "fn-service"
    secrets_path: str = "/etc/secrets/kc"
    token_cache_ttl: int = 0
    login_attempts: int = 3
    login_backoff: float = 1.5

    @model_validator(mode="after")
    def default_token_checks(self):
        """
        How access tokens are checked (ADR 0035). `issuer` is Keycloak's address on the node's host, which the chart sets;
        `allowed_clients` is the comma-separated client ids whose tokens are accepted (the token's azp). A value left
        unset defaults to this realm's address and the Keycloak client.
        """
        if self.issuer is None:
            self.issuer = f"{self.url}/realms/{self.realm}"
        if self.allowed_clients is None:
            self.allowed_clients = self.client
        return self


class ServicesSettings(shared.EnvSettings):
    """External services called by the API."""
    dagster: DagsterSettings = Field(default_factory=DagsterSettings)
    keycloak: KeycloakSettings = Field(default_factory=KeycloakSettings)


class TaskLimitsSettings(shared.EnvSettings):
    """Limits applied to task specifications."""
    model_config = SettingsConfigDict(env_prefix="TASKS_LIMITS_")

    max_cpu: str
    max_memory: str
    default_limit_cpu: str
    default_limit_memory: str


class TasksSettings(shared.EnvSettings):
    """API task settings."""
    limits: TaskLimitsSettings = Field(default_factory=TaskLimitsSettings)
